from __future__ import annotations

from dataclasses import dataclass

from app.modules.ai_rag.protocols import EmbeddingProvider, ElasticsearchBm25Store, MilvusDenseStore
from app.modules.ai_rag.retrieval import RagRetrievalService
from app.modules.ai_rag.types import KnowledgeDomain, RagConfig, RagResult, RetrievalFilter


@dataclass(frozen=True)
class DomainStoreConfig:
    domain: KnowledgeDomain
    milvus_collection: str
    elasticsearch_index: str
    requires_user_id: bool


@dataclass(frozen=True)
class DomainRetrievalRequest:
    domain: KnowledgeDomain
    query: str
    city_code: str | None
    user_id: str | None = None

    def __post_init__(self) -> None:
        if self.domain is KnowledgeDomain.USER_MEMORY and not self.user_id:
            raise ValueError("user_memory retrieval requires user_id")
        if self.domain is not KnowledgeDomain.USER_MEMORY and self.user_id is not None:
            raise ValueError("public retrieval must not include user_id")


class RagCatalog:
    """Selects one fixed domain store before hybrid retrieval begins."""

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        stores: dict[KnowledgeDomain, tuple[MilvusDenseStore, ElasticsearchBm25Store]],
        configs: dict[KnowledgeDomain, DomainStoreConfig],
        config: RagConfig | None = None,
    ) -> None:
        if set(stores) != set(configs):
            raise ValueError("RAG stores and domain configurations must match")
        self.embeddings = embeddings
        self.stores = stores
        self.configs = configs
        self.config = config or RagConfig()

    def store_for(self, domain: KnowledgeDomain) -> DomainStoreConfig:
        return self.configs[domain]

    async def retrieve(self, request: DomainRetrievalRequest) -> RagResult:
        milvus, elasticsearch = self.stores[request.domain]
        filters = RetrievalFilter(
            city_code=None if request.domain is KnowledgeDomain.USER_MEMORY else request.city_code,
            visibility="private" if request.domain is KnowledgeDomain.USER_MEMORY else "public",
            status="reviewed",
            knowledge_domain=request.domain,
            user_id=request.user_id,
        )
        return await RagRetrievalService(
            self.embeddings, milvus, elasticsearch, self.config
        ).retrieve(request.query, city_code=request.city_code, filters=filters)
