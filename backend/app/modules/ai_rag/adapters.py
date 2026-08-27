from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch
    from pymilvus import MilvusClient

from app.modules.ai_rag.types import (
    KnowledgeChunk,
    AuthorityLevel,
    KnowledgeDomain,
    KnowledgeMetadata,
    KnowledgeSourceType,
    RetrievedChunk,
    RetrievalFilter,
)


_LEGACY_METADATA_FIELDS = (
    "document_id",
    "chunk_id",
    "source_type",
    "source_id",
    "city_code",
    "poi_id",
    "language",
    "visibility",
    "status",
    "source_updated_at",
    "content_hash",
)
_DOMAIN_METADATA_FIELDS = (
    "knowledge_domain",
    "authority_level",
    "reviewed_at",
    "next_review_at",
    "source_version",
    "supersedes_document_id",
    "user_id",
)
_VECTOR_FIELD = "embedding"


class OpenAICompatibleEmbeddingProvider:
    """Embedding client for an OpenAI-compatible ``POST /embeddings`` endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        dimensions: int,
        timeout: float,
        send_dimensions: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or not model:
            raise ValueError("base_url and model are required")
        if dimensions < 1 or timeout <= 0:
            raise ValueError("dimensions and timeout must be positive")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout
        self.send_dimensions = send_dimensions
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await self._embed(list(texts))

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        payload: dict[str, object] = {"model": self.model, "input": inputs}
        if self.send_dimensions:
            payload["dimensions"] = self.dimensions
        response = await self.client.post(
            f"{self.base_url}/embeddings",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(records, list) or len(records) != len(inputs):
            raise ValueError("Embedding endpoint returned a vector count that does not match inputs")

        try:
            ordered = sorted(records, key=lambda record: record["index"])
            vectors = [record["embedding"] for record in ordered]
        except (KeyError, TypeError):
            raise ValueError("Embedding endpoint returned an invalid OpenAI-compatible response") from None
        if [record["index"] for record in ordered] != list(range(len(inputs))):
            raise ValueError("Embedding endpoint returned invalid embedding indexes")
        return [self._validate_vector(vector) for vector in vectors]

    def _validate_vector(self, vector: object) -> list[float]:
        if not isinstance(vector, list) or len(vector) != self.dimensions:
            raise ValueError(f"Embedding endpoint returned a vector with dimensions other than {self.dimensions}")
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
            raise ValueError("Embedding endpoint returned a non-finite vector value")
        return [float(value) for value in vector]


class ZillizMilvusDenseStore:
    """Dense retrieval adapter for a Zilliz Cloud managed Milvus collection."""

    def __init__(
        self,
        *,
        uri: str,
        token: str,
        collection_name: str,
        dimensions: int,
        include_domain_metadata: bool = False,
        client: Any | None = None,
    ) -> None:
        if not uri or not token or not collection_name:
            raise ValueError("uri, token, and collection_name are required")
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        self.collection_name = collection_name
        self.dimensions = dimensions
        self.include_domain_metadata = include_domain_metadata
        if client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as error:
                raise RuntimeError("pymilvus is required for a Zilliz Milvus connector") from error
            client = MilvusClient(uri=uri, token=token)
        self.client = client

    async def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)

    async def ensure_collection(self) -> None:
        exists = await asyncio.to_thread(self.client.has_collection, collection_name=self.collection_name)
        if exists:
            return
        try:
            from pymilvus import DataType
        except ImportError as error:
            raise RuntimeError("pymilvus is required to provision a Zilliz collection") from error

        def create() -> None:
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=256)
            schema.add_field(field_name=_VECTOR_FIELD, datatype=DataType.FLOAT_VECTOR, dim=self.dimensions)
            schema.add_field(field_name="page_content", datatype=DataType.VARCHAR, max_length=65535)
            schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=256)
            schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=64)
            schema.add_field(field_name="source_id", datatype=DataType.VARCHAR, max_length=256)
            schema.add_field(field_name="city_code", datatype=DataType.VARCHAR, max_length=64)
            schema.add_field(field_name="poi_id", datatype=DataType.VARCHAR, max_length=256)
            schema.add_field(field_name="language", datatype=DataType.VARCHAR, max_length=32)
            schema.add_field(field_name="visibility", datatype=DataType.VARCHAR, max_length=32)
            schema.add_field(field_name="status", datatype=DataType.VARCHAR, max_length=32)
            schema.add_field(field_name="source_updated_at", datatype=DataType.VARCHAR, max_length=64)
            schema.add_field(field_name="content_hash", datatype=DataType.VARCHAR, max_length=128)
            if self.include_domain_metadata:
                schema.add_field(field_name="knowledge_domain", datatype=DataType.VARCHAR, max_length=32)
                schema.add_field(field_name="authority_level", datatype=DataType.VARCHAR, max_length=32)
                schema.add_field(field_name="reviewed_at", datatype=DataType.VARCHAR, max_length=64)
                schema.add_field(field_name="next_review_at", datatype=DataType.VARCHAR, max_length=64)
                schema.add_field(field_name="source_version", datatype=DataType.VARCHAR, max_length=64)
                schema.add_field(field_name="supersedes_document_id", datatype=DataType.VARCHAR, max_length=256)
                schema.add_field(field_name="user_id", datatype=DataType.VARCHAR, max_length=256)
            index_params = self.client.prepare_index_params()
            index_params.add_index(field_name=_VECTOR_FIELD, index_type="AUTOINDEX", metric_type="COSINE")
            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params,
            )

        await asyncio.to_thread(create)

    async def upsert(self, chunks: Sequence[KnowledgeChunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Chunk and vector counts must match")
        records = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            records.append({_VECTOR_FIELD: self._validate_vector(vector), **_chunk_record(chunk, self.include_domain_metadata)})
        if records:
            await asyncio.to_thread(self.client.upsert, collection_name=self.collection_name, data=records)

    async def search(
        self, vector: Sequence[float], *, top_k: int, filters: RetrievalFilter
    ) -> list[RetrievedChunk]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        results = await asyncio.to_thread(
            self.client.search,
            collection_name=self.collection_name,
            data=[self._validate_vector(vector)],
            filter=_milvus_filter(filters, include_domain_metadata=self.include_domain_metadata),
            limit=top_k,
            output_fields=["page_content", *_LEGACY_METADATA_FIELDS, *(_DOMAIN_METADATA_FIELDS if self.include_domain_metadata else ())],
        )
        hits = results[0] if results else []
        return [_retrieved_chunk(_milvus_hit_fields(hit), float(_value(hit, "distance")), "milvus") for hit in hits]

    async def delete_document(self, document_id: str) -> None:
        if not document_id:
            raise ValueError("document_id is required")
        await asyncio.to_thread(
            self.client.delete,
            collection_name=self.collection_name,
            filter=f"document_id == {json.dumps(document_id)}",
        )

    def _validate_vector(self, vector: Sequence[float]) -> list[float]:
        values = [float(value) for value in vector]
        if len(values) != self.dimensions or not all(math.isfinite(value) for value in values):
            raise ValueError(f"Milvus vectors must contain {self.dimensions} finite values")
        return values


class ElasticsearchAsyncBm25Store:
    """Async Elasticsearch projection for BM25 retrieval of knowledge chunks."""

    def __init__(
        self,
        *,
        hosts: str | Sequence[str] | None,
        index_name: str,
        include_domain_metadata: bool = False,
        client: Any | None = None,
    ) -> None:
        if not index_name:
            raise ValueError("index_name is required")
        if client is None and not hosts:
            raise ValueError("hosts are required when no Elasticsearch client is injected")
        self.index_name = index_name
        self.include_domain_metadata = include_domain_metadata
        owns_client = client is None
        if owns_client:
            try:
                from elasticsearch import AsyncElasticsearch
            except ImportError as error:
                raise RuntimeError("elasticsearch is required for an Elasticsearch connector") from error
            client = AsyncElasticsearch(hosts=hosts)
        self._owns_client = owns_client
        self.client = client

    async def ensure_index(self) -> None:
        exists = await self.client.indices.exists(index=self.index_name)
        if exists:
            return
        await self.client.indices.create(
            index=self.index_name,
            mappings={
                "properties": {
                    "page_content": {"type": "text"},
                    "document_id": {"type": "keyword"},
                    "chunk_id": {"type": "keyword"},
                    "source_type": {"type": "keyword"},
                    "source_id": {"type": "keyword"},
                    "city_code": {"type": "keyword"},
                    "poi_id": {"type": "keyword"},
                    "language": {"type": "keyword"},
                    "visibility": {"type": "keyword"},
                    "status": {"type": "keyword"},
                    "source_updated_at": {"type": "date"},
                    "content_hash": {"type": "keyword"},
                    **(
                        {
                            "knowledge_domain": {"type": "keyword"},
                            "authority_level": {"type": "keyword"},
                            "reviewed_at": {"type": "date"},
                            "next_review_at": {"type": "date"},
                            "source_version": {"type": "keyword"},
                            "supersedes_document_id": {"type": "keyword"},
                            "user_id": {"type": "keyword"},
                        }
                        if self.include_domain_metadata
                        else {}
                    ),
                }
            },
        )

    async def index(self, chunks: Sequence[KnowledgeChunk]) -> None:
        if not chunks:
            return
        operations: list[dict[str, Any]] = []
        for chunk in chunks:
            operations.extend(
                ({"index": {"_index": self.index_name, "_id": chunk.metadata.chunk_id}}, _elasticsearch_record(chunk, self.include_domain_metadata))
            )
        response = await self.client.bulk(operations=operations, refresh="wait_for")
        if response.get("errors"):
            failed = next(
                (
                    item
                    for item in response.get("items", [])
                    if isinstance(item, Mapping)
                    and isinstance(item.get("index"), Mapping)
                    and item["index"].get("error")
                ),
                None,
            )
            detail = failed["index"].get("error") if failed else None
            raise RuntimeError(f"Elasticsearch rejected one or more knowledge chunks: {detail}")

    async def search(
        self, query: str, *, top_k: int, filters: RetrievalFilter
    ) -> list[RetrievedChunk]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        response = await self.client.search(
            index=self.index_name,
            size=top_k,
            query={
                "bool": {
                    "must": [{"match": {"page_content": {"query": query}}}],
                    "filter": _elasticsearch_filters(filters, include_domain_metadata=self.include_domain_metadata),
                }
            },
        )
        return [
            _retrieved_chunk(hit["_source"], float(hit["_score"]), "elasticsearch")
            for hit in response["hits"]["hits"]
        ]

    async def delete_document(self, document_id: str) -> None:
        if not document_id:
            raise ValueError("document_id is required")
        await self.client.delete_by_query(
            index=self.index_name,
            query={"term": {"document_id": document_id}},
            refresh=True,
            conflicts="proceed",
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.close()


def _chunk_record(chunk: KnowledgeChunk, include_domain_metadata: bool = False) -> dict[str, Any]:
    metadata = chunk.metadata
    record = {
        "page_content": chunk.page_content,
        "document_id": metadata.document_id,
        "chunk_id": metadata.chunk_id,
        "source_type": metadata.source_type.value,
        "source_id": metadata.source_id,
        "city_code": metadata.city_code or "",
        "poi_id": metadata.poi_id or "",
        "language": metadata.language,
        "visibility": metadata.visibility,
        "status": metadata.status,
        "source_updated_at": metadata.source_updated_at.isoformat(),
        "content_hash": metadata.content_hash,
    }
    if include_domain_metadata:
        if metadata.knowledge_domain is None:
            raise ValueError("domain stores require knowledge_domain")
        record.update(
            knowledge_domain=metadata.knowledge_domain.value,
            authority_level=metadata.authority_level.value,
            reviewed_at=metadata.reviewed_at.isoformat() if metadata.reviewed_at else "",
            next_review_at=metadata.next_review_at.isoformat() if metadata.next_review_at else "",
            source_version=metadata.source_version,
            supersedes_document_id=metadata.supersedes_document_id or "",
            user_id=metadata.user_id or "",
        )
    return record


def _elasticsearch_record(chunk: KnowledgeChunk, include_domain_metadata: bool = False) -> dict[str, Any]:
    record = _chunk_record(chunk, include_domain_metadata)
    if include_domain_metadata:
        for field in ("reviewed_at", "next_review_at"):
            if record[field] == "":
                record[field] = None
    return record


def _retrieved_chunk(record: Mapping[str, Any], score: float, source: str) -> RetrievedChunk:
    try:
        return RetrievedChunk(
            chunk=KnowledgeChunk(
                page_content=record["page_content"],
                metadata=KnowledgeMetadata(
                    document_id=record["document_id"],
                    chunk_id=record["chunk_id"],
                    source_type=KnowledgeSourceType(record["source_type"]),
                    source_id=record["source_id"],
                    city_code=record["city_code"] or None,
                    poi_id=record["poi_id"] or None,
                    language=record["language"],
                    visibility=record["visibility"],
                    status=record["status"],
                    source_updated_at=datetime.fromisoformat(record["source_updated_at"]),
                    content_hash=record["content_hash"],
                    knowledge_domain=KnowledgeDomain(record["knowledge_domain"]) if record.get("knowledge_domain") else None,
                    authority_level=AuthorityLevel(record.get("authority_level", "official")),
                    reviewed_at=datetime.fromisoformat(record["reviewed_at"]) if record.get("reviewed_at") else None,
                    next_review_at=datetime.fromisoformat(record["next_review_at"]) if record.get("next_review_at") else None,
                    source_version=record.get("source_version", "1"),
                    supersedes_document_id=record.get("supersedes_document_id") or None,
                    user_id=record.get("user_id") or None,
                ),
            ),
            score=score,
            source=source,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{source} returned an invalid knowledge chunk") from error


def _milvus_filter(filters: RetrievalFilter, *, include_domain_metadata: bool) -> str:
    fields = [
        ("visibility", filters.visibility),
        ("status", filters.status),
    ]
    if include_domain_metadata and filters.knowledge_domain:
        fields.append(("knowledge_domain", filters.knowledge_domain.value))
    if filters.city_code:
        fields.insert(0, ("city_code", filters.city_code))
    if filters.user_id and include_domain_metadata:
        fields.append(("user_id", filters.user_id))
    return " and ".join(f"{field} == {json.dumps(value)}" for field, value in fields)


def _elasticsearch_filters(filters: RetrievalFilter, *, include_domain_metadata: bool) -> list[dict[str, dict[str, str]]]:
    predicates = [
        {"term": {"visibility": filters.visibility}},
        {"term": {"status": filters.status}},
    ]
    if include_domain_metadata and filters.knowledge_domain:
        predicates.append({"term": {"knowledge_domain": filters.knowledge_domain.value}})
    if filters.city_code:
        predicates.insert(0, {"term": {"city_code": filters.city_code}})
    if filters.user_id and include_domain_metadata:
        predicates.append({"term": {"user_id": filters.user_id}})
    return predicates


def _milvus_hit_fields(hit: Any) -> Mapping[str, Any]:
    entity = _value(hit, "entity")
    if isinstance(entity, Mapping):
        return entity
    if isinstance(hit, Mapping):
        return hit
    raise ValueError("Milvus returned an invalid search hit")


def _value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value[name]
    return getattr(value, name)
