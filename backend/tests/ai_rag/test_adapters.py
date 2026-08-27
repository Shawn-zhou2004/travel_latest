from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime

import httpx
import pytest

from app.modules.ai_rag.adapters import (
    ElasticsearchAsyncBm25Store,
    OpenAICompatibleEmbeddingProvider,
    ZillizMilvusDenseStore,
)
from app.modules.ai_rag.types import (
    AuthorityLevel,
    KnowledgeChunk,
    KnowledgeDomain,
    KnowledgeMetadata,
    KnowledgeSourceType,
    RetrievalFilter,
)


def _chunk() -> KnowledgeChunk:
    return KnowledgeChunk(
        "West Lake has a public walking route.",
        KnowledgeMetadata(
            document_id="doc-1",
            chunk_id="chunk-1",
            source_type=KnowledgeSourceType.POI,
            source_id="amap-1",
            city_code="330100",
            poi_id="poi-1",
            language="zh-CN",
            visibility="public",
            status="reviewed",
            source_updated_at=datetime(2026, 8, 4, 9, 30, tzinfo=UTC),
            content_hash="content-hash",
        ),
    )


def test_openai_compatible_embeddings_send_injected_configuration_and_validate_response() -> None:
    async def scenario() -> None:
        request: httpx.Request | None = None

        async def handler(received: httpx.Request) -> httpx.Response:
            nonlocal request
            request = received
            return httpx.Response(200, json={"data": [{"index": 1, "embedding": [3, 4]}, {"index": 0, "embedding": [1, 2]}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenAICompatibleEmbeddingProvider(
            api_key="secret", base_url="https://embedding.example/v1/", model="embedding-test", dimensions=2, timeout=7, send_dimensions=True, client=client
        )
        assert await adapter.embed_documents(["first", "second"]) == [[1.0, 2.0], [3.0, 4.0]]
        assert request is not None
        assert request.url == "https://embedding.example/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer secret"
        assert json.loads(request.content) == {"model": "embedding-test", "input": ["first", "second"], "dimensions": 2}
        await client.aclose()

    asyncio.run(scenario())


def test_openai_compatible_embeddings_reject_wrong_dimensions() -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1]}]})))
        adapter = OpenAICompatibleEmbeddingProvider(api_key=None, base_url="https://embedding.example", model="test", dimensions=2, timeout=1, client=client)
        with pytest.raises(ValueError, match="dimensions"):
            await adapter.embed_query("west lake")
        await client.aclose()

    asyncio.run(scenario())


def test_milvus_upsert_and_search_preserve_metadata_filters_and_use_a_worker_thread() -> None:
    async def scenario() -> None:
        class Client:
            def __init__(self) -> None:
                self.upsert_request: dict | None = None
                self.search_request: dict | None = None
                self.delete_request: dict | None = None
                self.thread_ids: list[int] = []

            def upsert(self, **kwargs: object) -> None:
                self.thread_ids.append(threading.get_ident())
                self.upsert_request = kwargs

            def search(self, **kwargs: object) -> list[list[dict]]:
                self.thread_ids.append(threading.get_ident())
                self.search_request = kwargs
                record = kwargs["data"] and self.upsert_request["data"][0].copy()  # type: ignore[index]
                return [[{"distance": 0.91, "entity": record}]]

            def delete(self, **kwargs: object) -> None:
                self.thread_ids.append(threading.get_ident())
                self.delete_request = kwargs

        client = Client()
        adapter = ZillizMilvusDenseStore(uri="https://zilliz.example", token="token", collection_name="knowledge", dimensions=2, client=client)
        await adapter.upsert([_chunk()], [[0.1, 0.2]])
        results = await adapter.search([0.2, 0.1], top_k=20, filters=RetrievalFilter(city_code="330100"))
        await adapter.delete_document("doc-1")
        assert client.upsert_request is not None and client.search_request is not None
        assert client.upsert_request["data"][0]["embedding"] == [0.1, 0.2]
        assert client.upsert_request["data"][0]["source_updated_at"] == "2026-08-04T09:30:00+00:00"
        assert client.search_request["filter"] == 'city_code == "330100" and visibility == "public" and status == "reviewed"'
        assert client.search_request["output_fields"] == ["page_content", "document_id", "chunk_id", "source_type", "source_id", "city_code", "poi_id", "language", "visibility", "status", "source_updated_at", "content_hash"]
        assert client.delete_request == {"collection_name": "knowledge", "filter": 'document_id == "doc-1"'}
        assert client.thread_ids and all(thread_id != threading.get_ident() for thread_id in client.thread_ids)
        assert results[0].chunk == _chunk()
        assert results[0].score == 0.91 and results[0].source == "milvus"

    asyncio.run(scenario())


def test_elasticsearch_indexes_and_searches_the_same_metadata_contract() -> None:
    async def scenario() -> None:
        class Client:
            def __init__(self) -> None:
                self.operations: list[dict] | None = None
                self.search_request: dict | None = None
                self.delete_request: dict | None = None

            async def bulk(self, **kwargs: object) -> dict:
                self.operations = kwargs["operations"]  # type: ignore[assignment]
                return {"errors": False}

            async def search(self, **kwargs: object) -> dict:
                self.search_request = kwargs
                return {"hits": {"hits": [{"_score": 4.5, "_source": self.operations[1]}]}}

            async def delete_by_query(self, **kwargs: object) -> dict:
                self.delete_request = kwargs
                return {"deleted": 1, "failures": []}

        client = Client()
        adapter = ElasticsearchAsyncBm25Store(hosts=None, index_name="travel-knowledge", client=client)
        await adapter.index([_chunk()])
        results = await adapter.search("West Lake", top_k=20, filters=RetrievalFilter(city_code="330100"))
        await adapter.delete_document("doc-1")
        assert client.operations == [
            {"index": {"_index": "travel-knowledge", "_id": "chunk-1"}},
            {
                "page_content": "West Lake has a public walking route.", "document_id": "doc-1", "chunk_id": "chunk-1", "source_type": "poi", "source_id": "amap-1", "city_code": "330100", "poi_id": "poi-1", "language": "zh-CN", "visibility": "public", "status": "reviewed", "source_updated_at": "2026-08-04T09:30:00+00:00", "content_hash": "content-hash",
            },
        ]
        assert client.search_request["query"]["bool"]["filter"] == [{"term": {"city_code": "330100"}}, {"term": {"visibility": "public"}}, {"term": {"status": "reviewed"}}]
        assert client.delete_request == {"index": "travel-knowledge", "query": {"term": {"document_id": "doc-1"}}, "refresh": True, "conflicts": "proceed"}
        assert results[0].chunk == _chunk()
        assert results[0].score == 4.5 and results[0].source == "elasticsearch"

    asyncio.run(scenario())


def test_domain_store_writes_required_domain_metadata() -> None:
    async def scenario() -> None:
        class Client:
            def __init__(self) -> None:
                self.request: dict | None = None

            def upsert(self, **kwargs: object) -> None:
                self.request = kwargs

        client = Client()
        adapter = ZillizMilvusDenseStore(
            uri="https://zilliz.example",
            token="token",
            collection_name="official",
            dimensions=2,
            include_domain_metadata=True,
            client=client,
        )
        document = _chunk().metadata
        chunk = KnowledgeChunk(
            "West Lake has a public walking route.",
            KnowledgeMetadata(
                document_id=document.document_id,
                chunk_id=document.chunk_id,
                source_type=document.source_type,
                source_id=document.source_id,
                city_code=document.city_code,
                poi_id=document.poi_id,
                language=document.language,
                visibility=document.visibility,
                status=document.status,
                source_updated_at=document.source_updated_at,
                content_hash=document.content_hash,
                knowledge_domain=KnowledgeDomain.OFFICIAL,
                authority_level=AuthorityLevel.OFFICIAL,
            ),
        )
        await adapter.upsert([chunk], [[0.1, 0.2]])
        assert client.request is not None
        assert client.request["data"][0]["knowledge_domain"] == "official"
        assert client.request["data"][0]["authority_level"] == "official"

    asyncio.run(scenario())


def test_domain_elasticsearch_writes_null_for_optional_dates() -> None:
    async def scenario() -> None:
        class Client:
            def __init__(self) -> None:
                self.operations = None

            async def bulk(self, **kwargs: object) -> dict:
                self.operations = kwargs["operations"]
                return {"errors": False}

        client = Client()
        adapter = ElasticsearchAsyncBm25Store(
            hosts=None, index_name="official", include_domain_metadata=True, client=client
        )
        metadata = _chunk().metadata
        chunk = KnowledgeChunk(
            "West Lake has a public walking route.",
            KnowledgeMetadata(
                document_id=metadata.document_id,
                chunk_id=metadata.chunk_id,
                source_type=metadata.source_type,
                source_id=metadata.source_id,
                city_code=metadata.city_code,
                poi_id=metadata.poi_id,
                language=metadata.language,
                visibility=metadata.visibility,
                status=metadata.status,
                source_updated_at=metadata.source_updated_at,
                content_hash=metadata.content_hash,
                knowledge_domain=KnowledgeDomain.OFFICIAL,
            ),
        )
        await adapter.index([chunk])
        assert client.operations[1]["reviewed_at"] is None
        assert client.operations[1]["next_review_at"] is None

    asyncio.run(scenario())
