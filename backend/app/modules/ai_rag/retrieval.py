from __future__ import annotations

import asyncio

from app.modules.ai_rag.protocols import EmbeddingProvider, ElasticsearchBm25Store, MilvusDenseStore
from app.modules.ai_rag.types import (
    Citation,
    RagConfig,
    RagContextItem,
    RagResult,
    RagStatus,
    RetrievedChunk,
    RetrievalFilter,
)


class RagDependencyUnavailable(RuntimeError):
    """A managed retrieval dependency could not serve a request."""


class RagRetrievalService:
    """The sole phase-one RAG retrieval pipeline: dense + BM25 -> RRF -> citations."""

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        milvus: MilvusDenseStore,
        elasticsearch: ElasticsearchBm25Store,
        config: RagConfig | None = None,
    ) -> None:
        self.embeddings = embeddings
        self.milvus = milvus
        self.elasticsearch = elasticsearch
        self.config = config or RagConfig()

    async def retrieve(
        self, query: str, *, city_code: str | None, filters: RetrievalFilter | None = None
    ) -> RagResult:
        if not query.strip():
            return RagResult(RagStatus.NO_RESULTS, message="A non-empty retrieval query is required.")
        filters = filters or RetrievalFilter(city_code=city_code)
        try:
            query_vector = await self.embeddings.embed_query(query)
            dense, bm25 = await asyncio.gather(
                self.milvus.search(query_vector, top_k=self.config.dense_top_k, filters=filters),
                self.elasticsearch.search(query, top_k=self.config.bm25_top_k, filters=filters),
            )
        except Exception as error:
            return RagResult(RagStatus.UNAVAILABLE, message=f"Travel knowledge is unavailable: {error}")

        contexts = self._rrf(dense, bm25, filters)
        if not contexts:
            scope = "city" if filters.city_code else "official travel knowledge base"
            return RagResult(RagStatus.NO_RESULTS, message=f"No reviewed {scope} matched this query.")
        if contexts[0].score < self.config.min_score:
            return RagResult(
                RagStatus.CLARIFICATION_REQUIRED,
                message="Available sources are too low-confidence to use as travel facts.",
            )
        return RagResult(RagStatus.AVAILABLE, contexts=tuple(contexts))

    def _rrf(
        self, dense: list[RetrievedChunk], bm25: list[RetrievedChunk], filters: RetrievalFilter
    ) -> list[RagContextItem]:
        merged: dict[str, tuple[RetrievedChunk, float]] = {}
        for results in (dense, bm25):
            for rank, result in enumerate(results, start=1):
                metadata = result.chunk.metadata
                if (
                    (filters.city_code and metadata.city_code != filters.city_code)
                    or metadata.visibility != filters.visibility
                    or metadata.status != filters.status
                    or (filters.knowledge_domain and metadata.knowledge_domain != filters.knowledge_domain)
                    or (filters.user_id and metadata.user_id != filters.user_id)
                ):
                    continue
                key = metadata.content_hash
                previous = merged.get(key)
                score = (previous[1] if previous else 0.0) + 1 / (self.config.rrf_k + rank)
                merged[key] = (previous[0] if previous else result, score)

        # Normalize against the best possible two-retriever rank so min_score is meaningful.
        best_possible = 2 / (self.config.rrf_k + 1)
        ranked = sorted(merged.values(), key=lambda value: value[1], reverse=True)
        return [
            RagContextItem(
                content=result.chunk.page_content,
                citation=Citation.from_chunk(result.chunk),
                score=score / best_possible,
            )
            for result, score in ranked[: self.config.final_top_k]
        ]
