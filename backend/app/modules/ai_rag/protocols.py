from __future__ import annotations

from typing import Protocol, Sequence

from app.modules.ai_rag.types import KnowledgeChunk, RetrievedChunk, RetrievalFilter


class EmbeddingProvider(Protocol):
    """Compatible with LangChain Embeddings; implementations may wrap any provider."""

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class MilvusDenseStore(Protocol):
    """Managed Milvus collection adapter for travel knowledge dense vectors."""

    async def upsert(self, chunks: Sequence[KnowledgeChunk], vectors: Sequence[Sequence[float]]) -> None: ...

    async def search(
        self, vector: Sequence[float], *, top_k: int, filters: RetrievalFilter
    ) -> list[RetrievedChunk]: ...

    async def delete_document(self, document_id: str) -> None: ...


class ElasticsearchBm25Store(Protocol):
    """Elasticsearch adapter for the BM25 projection of the same chunks."""

    async def index(self, chunks: Sequence[KnowledgeChunk]) -> None: ...

    async def search(
        self, query: str, *, top_k: int, filters: RetrievalFilter
    ) -> list[RetrievedChunk]: ...

    async def delete_document(self, document_id: str) -> None: ...
