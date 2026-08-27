from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.modules.ai_rag.retrieval import RagRetrievalService
from app.modules.ai_rag.types import (
    KnowledgeChunk,
    KnowledgeMetadata,
    KnowledgeSourceType,
    RagStatus,
    RetrievedChunk,
)


def chunk(chunk_id: str, content: str, *, city_code: str = "330100", status: str = "reviewed") -> KnowledgeChunk:
    return KnowledgeChunk(
        content,
        KnowledgeMetadata(
            document_id=f"document-{chunk_id}",
            chunk_id=chunk_id,
            source_type=KnowledgeSourceType.COMMUNITY,
            source_id=f"source-{chunk_id}",
            city_code=city_code,
            poi_id=None,
            language="zh-CN",
            visibility="public",
            status=status,
            source_updated_at=datetime(2026, 8, 1, tzinfo=UTC),
            content_hash=f"hash-{content}",
        ),
    )


class FakeEmbeddings:
    async def embed_query(self, text: str) -> list[float]:
        assert text == "west lake"
        return [0.5, 0.5]


class FakeMilvus:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.request: tuple[int, str] | None = None

    async def search(self, _vector: list[float], *, top_k: int, filters: object) -> list[RetrievedChunk]:
        self.request = (top_k, filters.city_code)
        return self.results


class FakeElasticsearch:
    def __init__(self, results: list[RetrievedChunk], error: Exception | None = None) -> None:
        self.results = results
        self.error = error
        self.request: tuple[int, str] | None = None

    async def search(self, _query: str, *, top_k: int, filters: object) -> list[RetrievedChunk]:
        if self.error:
            raise self.error
        self.request = (top_k, filters.city_code)
        return self.results


def test_retrieval_uses_required_top_k_rrf_dedupes_and_returns_citations() -> None:
    async def scenario() -> None:
        shared = chunk("shared", "Shared reviewed source")
        dense_only = chunk("dense", "Dense only")
        other_city = chunk("other", "Wrong city", city_code="440100")
        milvus = FakeMilvus([
            RetrievedChunk(shared, 0.98, "milvus"),
            RetrievedChunk(dense_only, 0.80, "milvus"),
            RetrievedChunk(other_city, 0.99, "milvus"),
        ])
        elasticsearch = FakeElasticsearch([RetrievedChunk(shared, 10.0, "elasticsearch")])
        result = await RagRetrievalService(FakeEmbeddings(), milvus, elasticsearch).retrieve(
            "west lake", city_code="330100"
        )

        assert result.status is RagStatus.AVAILABLE
        assert milvus.request == (20, "330100")
        assert elasticsearch.request == (20, "330100")
        assert [item.content for item in result.contexts] == ["Shared reviewed source", "Dense only"]
        assert result.contexts[0].citation.source_id == "source-shared"
        assert result.contexts[0].citation.source_updated_at == datetime(2026, 8, 1, tzinfo=UTC)
        assert result.contexts[0].score > result.contexts[1].score

    asyncio.run(scenario())


def test_retrieval_returns_explicit_clarification_no_results_and_unavailable_states() -> None:
    async def scenario() -> None:
        global_source = chunk("global", "Reviewed official travel source")
        global_result = await RagRetrievalService(
            FakeEmbeddings(),
            FakeMilvus([RetrievedChunk(global_source, 0.9, "milvus")]),
            FakeElasticsearch([RetrievedChunk(global_source, 0.9, "elasticsearch")]),
        ).retrieve("west lake", city_code=None)
        assert global_result.status is RagStatus.AVAILABLE

        no_results = await RagRetrievalService(FakeEmbeddings(), FakeMilvus([]), FakeElasticsearch([])).retrieve(
            "west lake", city_code="330100"
        )
        assert no_results.status is RagStatus.NO_RESULTS

        unavailable = await RagRetrievalService(
            FakeEmbeddings(), FakeMilvus([]), FakeElasticsearch([], RuntimeError("ES timeout"))
        ).retrieve("west lake", city_code="330100")
        assert unavailable.status is RagStatus.UNAVAILABLE
        assert "ES timeout" in (unavailable.message or "")

    asyncio.run(scenario())
