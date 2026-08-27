from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.ai_rag.catalog import DomainStoreConfig, RagCatalog
from app.modules.ai_rag.types import (
    KnowledgeChunk,
    KnowledgeDomain,
    KnowledgeMetadata,
    KnowledgeSourceType,
    RetrievedChunk,
)
from app.modules.ai_workflows.contracts import GenerationRequest
from app.modules.ai_workflows.runtime import AIRuntime, DomainRagRetriever
from app.modules.ai_workflows.workflow import DependencyUnavailable


class FakeEmbeddings:
    async def embed_query(self, _text: str) -> list[float]:
        return [1.0]


class FakeStore:
    def __init__(self, results: list[RetrievedChunk] | None = None, error: Exception | None = None) -> None:
        self.results = results or []
        self.error = error
        self.filters: list[object] = []

    async def search(self, *_args: object, filters: object, **_kwargs: object) -> list[RetrievedChunk]:
        self.filters.append(filters)
        if self.error:
            raise self.error
        return self.results


def _chunk(domain: KnowledgeDomain, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        KnowledgeChunk(
            content,
            KnowledgeMetadata(
                document_id=f"{domain}-document",
                chunk_id=f"{domain}-chunk",
                source_type=KnowledgeSourceType.RULE,
                source_id=f"{domain}-source",
                city_code="330100",
                poi_id=None,
                language="zh-CN",
                visibility="public",
                status="reviewed",
                source_updated_at=datetime(2026, 8, 7, tzinfo=UTC),
                content_hash=f"{domain}-hash",
                knowledge_domain=domain,
            ),
        ),
        1.0,
        "fake",
    )


def _catalog(
    official: tuple[FakeStore, FakeStore], community: tuple[FakeStore, FakeStore]
) -> RagCatalog:
    configs = {
        domain: DomainStoreConfig(domain, f"{domain}_milvus", f"{domain}_elastic", False)
        for domain in (KnowledgeDomain.OFFICIAL, KnowledgeDomain.COMMUNITY)
    }
    return RagCatalog(
        FakeEmbeddings(),
        {KnowledgeDomain.OFFICIAL: official, KnowledgeDomain.COMMUNITY: community},
        configs,
    )


def _request() -> GenerationRequest:
    return GenerationRequest(
        "job-1", "user-1", "Plan a trip", "330100", datetime(2026, 9, 1).date(), datetime(2026, 9, 2).date()
    )


@pytest.mark.anyio
async def test_domain_retriever_degrades_when_official_is_unavailable() -> None:
    official = (FakeStore(error=RuntimeError("official offline")), FakeStore())
    community = (FakeStore([_chunk(KnowledgeDomain.COMMUNITY, "Community tip")]), FakeStore())

    citations = await DomainRagRetriever(_catalog(official, community)).retrieve(_request())

    assert [citation.content for citation in citations] == ["Community tip"]


@pytest.mark.anyio
async def test_domain_retriever_keeps_official_evidence_when_community_is_unavailable() -> None:
    official = (
        FakeStore([_chunk(KnowledgeDomain.OFFICIAL, "Official rule")]),
        FakeStore([_chunk(KnowledgeDomain.OFFICIAL, "Official rule")]),
    )
    community = (FakeStore(error=RuntimeError("community offline")), FakeStore())

    citations = await DomainRagRetriever(_catalog(official, community)).retrieve(_request())

    assert [citation.content for citation in citations] == ["Official rule"]
    assert community[0].filters[0].knowledge_domain is KnowledgeDomain.COMMUNITY


def test_runtime_uses_private_rag_profile_loader() -> None:
    runtime = object.__new__(AIRuntime)
    runtime.memory = object()
    runtime.domain_retrieval = type("DomainRuntime", (), {"catalog": object()})()
    runtime.generator = object()

    dependencies = runtime.dependencies()

    assert type(dependencies.profile_memory).__name__ == "PrivateMemoryProfileLoader"
