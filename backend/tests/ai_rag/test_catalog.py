from __future__ import annotations

import asyncio

from app.modules.ai_rag.catalog import DomainRetrievalRequest, DomainStoreConfig, RagCatalog
from app.modules.ai_rag.types import KnowledgeDomain


class FakeEmbeddings:
    async def embed_query(self, _text: str) -> list[float]:
        return [1.0]


class FakeDense:
    def __init__(self) -> None:
        self.filters = None

    async def search(self, _vector, *, top_k, filters):
        self.filters = filters
        return []


class FakeBm25:
    def __init__(self) -> None:
        self.filters = None

    async def search(self, _query, *, top_k, filters):
        self.filters = filters
        return []


def test_catalog_applies_private_user_filter_to_both_retrievers() -> None:
    async def scenario() -> None:
        dense, bm25 = FakeDense(), FakeBm25()
        catalog = RagCatalog(
            FakeEmbeddings(),
            {KnowledgeDomain.USER_MEMORY: (dense, bm25)},
            {
                KnowledgeDomain.USER_MEMORY: DomainStoreConfig(
                    KnowledgeDomain.USER_MEMORY, "user_memory_v1", "user_memory_v1", True
                )
            },
        )
        await catalog.retrieve(
            DomainRetrievalRequest(KnowledgeDomain.USER_MEMORY, "vegetarian", "330100", "user-a")
        )
        assert dense.filters.user_id == "user-a"
        assert bm25.filters.user_id == "user-a"
        assert dense.filters.visibility == "private"
        assert dense.filters.city_code is None
        assert bm25.filters.city_code is None

    asyncio.run(scenario())
