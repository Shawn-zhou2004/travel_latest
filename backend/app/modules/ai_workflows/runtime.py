from __future__ import annotations

from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.settings import Settings
from app.modules.ai_memory.private_retrieval import PrivateMemoryProfileLoader
from app.modules.ai_memory.postgres import AIMemoryRepository, AsyncpgPoolFactory, open_langgraph_checkpointer
from app.modules.ai_rag.adapters import (
    ElasticsearchAsyncBm25Store,
    OpenAICompatibleEmbeddingProvider,
    ZillizMilvusDenseStore,
)
from app.modules.ai_rag.catalog import DomainRetrievalRequest, DomainStoreConfig, RagCatalog
from app.modules.ai_rag.retrieval import RagRetrievalService
from app.modules.ai_rag.ingestion import KnowledgeIngestionService
from app.modules.ai_rag.types import KnowledgeDomain, RagConfig, RagResult, RagStatus
from app.modules.ai_workflows.contracts import (
    Citation,
    ConstraintCheck,
    GenerationRequest,
    RAGRetriever,
    VerifiedPoi,
    VerifiedPlanningCandidate,
)
from app.modules.ai_workflows.agent_draft import AgentStructuredDraftGenerator
from app.modules.ai_workflows.dashscope import DashScopeStructuredDraftGenerator
from app.modules.ai_workflows.live_sources import LiveSourceResolver, LiveSourceRetriever
from app.modules.ai_workflows.workflow import (
    ConstraintViolation,
    DependencyUnavailable,
    GenerationDependencies,
    LangGraphWorkflowFactory,
)
from app.modules.maps.service import AMapService, MapUnavailable
from app.modules.admin.models import OfficialKnowledgeSource, PoiCandidate
from app.integrations.mcp.websearch import MagicMcpWebSearchProvider, UnavailableWebSearchProvider


class LangChainRagRetriever:
    def __init__(self, service: RagRetrievalService) -> None:
        self.service = service

    async def retrieve(self, request: GenerationRequest) -> tuple[Citation, ...]:
        try:
            result = await self.service.retrieve(request.prompt, city_code=request.city_code)
        except Exception:
            return ()
        if result.status != RagStatus.AVAILABLE:
            return ()
        return tuple(
            Citation(
                document_id=item.citation.document_id,
                chunk_id=item.citation.chunk_id,
                source_type=item.citation.source_type.value,
                source_id=item.citation.source_id,
                city_code=item.citation.city_code or request.city_code,
                source_updated_at=item.citation.source_updated_at.isoformat(),
                content=item.content,
                poi_id=item.citation.poi_id,
            )
            for item in result.contexts
        )

# 官方域(OFFICIAL)和社区域(COMMUNITY)都尽力而为；不可用/无结果时返回空，由 live_sources 兜底
class DomainRagRetriever:
    """Retrieves official and community evidence; both are best-effort."""

    def __init__(self, catalog: RagCatalog) -> None:
        self.catalog = catalog

    async def retrieve(self, request: GenerationRequest) -> tuple[Citation, ...]:
        citations: list[Citation] = []
        for domain in (KnowledgeDomain.OFFICIAL, KnowledgeDomain.COMMUNITY):
            try:
                result = await self.catalog.retrieve(
                    DomainRetrievalRequest(domain, request.prompt, request.city_code)
                )
            except Exception:
                continue
            if result.status != RagStatus.AVAILABLE:
                continue
            citations.extend(self._citations(result, request))
        return tuple(citations)

    @staticmethod
    def _citations(result: RagResult, request: GenerationRequest) -> tuple[Citation, ...]:
        return tuple(
            Citation(
                document_id=item.citation.document_id,
                chunk_id=item.citation.chunk_id,
                source_type=item.citation.source_type.value,
                source_id=item.citation.source_id,
                city_code=item.citation.city_code or request.city_code,
                source_updated_at=item.citation.source_updated_at.isoformat(),
                content=item.content,
                poi_id=item.citation.poi_id,
            )
            for item in result.contexts
        )


@dataclass
class RetrievalRuntime:
    """The read-only dependencies needed by the administrative RAG probe."""

    embeddings: OpenAICompatibleEmbeddingProvider
    milvus: ZillizMilvusDenseStore
    elasticsearch: ElasticsearchAsyncBm25Store
    service: RagRetrievalService

    async def retrieve(self, query: str, *, city_code: str) -> RagResult:
        return await self.service.retrieve(query, city_code=city_code)

    async def close(self) -> None:
        await _close_retrieval_resources(self.embeddings, self.milvus, self.elasticsearch)


@dataclass
class DomainRetrievalRuntime:
    """Fixed domain stores prepared during the staged shared-RAG cutover."""

    embeddings: OpenAICompatibleEmbeddingProvider
    catalog: RagCatalog
    milvus_stores: tuple[ZillizMilvusDenseStore, ...]
    elasticsearch_stores: tuple[ElasticsearchAsyncBm25Store, ...]

    async def close(self) -> None:
        for store in self.elasticsearch_stores:
            await store.aclose()
        for store in self.milvus_stores:
            await store.close()
        await self.embeddings.aclose()


async def _close_retrieval_resources(
    embeddings: OpenAICompatibleEmbeddingProvider | None,
    milvus: ZillizMilvusDenseStore | None,
    elasticsearch: ElasticsearchAsyncBm25Store | None,
) -> None:
    for closer in (
        getattr(elasticsearch, "aclose", None),
        getattr(milvus, "close", None),
        getattr(embeddings, "aclose", None),
    ):
        if closer is not None:
            with suppress(Exception):
                await closer()


async def open_retrieval_runtime(settings: Settings | None = None) -> RetrievalRuntime:
    """Open only the embedding and retrieval stores required for a read probe."""

    settings = settings or Settings()
    embeddings: OpenAICompatibleEmbeddingProvider | None = None
    milvus: ZillizMilvusDenseStore | None = None
    elasticsearch: ElasticsearchAsyncBm25Store | None = None
    try:
        embeddings = OpenAICompatibleEmbeddingProvider(
            api_key=settings.embedding_api_key or settings.dashscope_api_key,
            base_url=settings.embedding_base_url or "",
            model=settings.embedding_model or "",
            dimensions=settings.embedding_dimensions,
            timeout=settings.embedding_timeout_seconds,
        )
        milvus = ZillizMilvusDenseStore(
            uri=settings.milvus_uri or "",
            token=settings.milvus_token or "",
            collection_name=settings.milvus_collection_travel_knowledge,
            dimensions=settings.embedding_dimensions,
        )
        elasticsearch = ElasticsearchAsyncBm25Store(
            hosts=settings.elasticsearch_url,
            index_name=settings.elasticsearch_index_travel_knowledge,
        )
        service = RagRetrievalService(
            embeddings,
            milvus,
            elasticsearch,
            RagConfig(
                dense_top_k=settings.rag_top_k_dense,
                bm25_top_k=settings.rag_top_k_bm25,
                final_top_k=settings.rag_top_k_final,
                min_score=settings.rag_min_score,
            ),
        )
        return RetrievalRuntime(embeddings, milvus, elasticsearch, service)
    except Exception:
        await _close_retrieval_resources(embeddings, milvus, elasticsearch)
        raise


async def open_domain_retrieval_runtime(settings: Settings | None = None) -> DomainRetrievalRuntime:
    """Open and provision only the three fixed domain projections."""

    settings = settings or Settings()
    embeddings = OpenAICompatibleEmbeddingProvider(
        api_key=settings.embedding_api_key or settings.dashscope_api_key,
        base_url=settings.embedding_base_url or "",
        model=settings.embedding_model or "",
        dimensions=settings.embedding_dimensions,
        timeout=settings.embedding_timeout_seconds,
    )
    configs = {
        KnowledgeDomain.OFFICIAL: DomainStoreConfig(
            KnowledgeDomain.OFFICIAL,
            settings.milvus_collection_official_knowledge,
            settings.elasticsearch_index_official_knowledge,
            False,
        ),
        KnowledgeDomain.COMMUNITY: DomainStoreConfig(
            KnowledgeDomain.COMMUNITY,
            settings.milvus_collection_community_knowledge,
            settings.elasticsearch_index_community_knowledge,
            False,
        ),
        KnowledgeDomain.USER_MEMORY: DomainStoreConfig(
            KnowledgeDomain.USER_MEMORY,
            settings.milvus_collection_user_memory,
            settings.elasticsearch_index_user_memory,
            True,
        ),
    }
    milvus_stores: list[ZillizMilvusDenseStore] = []
    elasticsearch_stores: list[ElasticsearchAsyncBm25Store] = []
    try:
        stores = {}
        for domain, config in configs.items():
            milvus = ZillizMilvusDenseStore(
                uri=settings.milvus_uri or "",
                token=settings.milvus_token or "",
                collection_name=config.milvus_collection,
                dimensions=settings.embedding_dimensions,
                include_domain_metadata=True,
            )
            elasticsearch = ElasticsearchAsyncBm25Store(
                hosts=settings.elasticsearch_url,
                index_name=config.elasticsearch_index,
                include_domain_metadata=True,
            )
            await milvus.ensure_collection()
            await elasticsearch.ensure_index()
            milvus_stores.append(milvus)
            elasticsearch_stores.append(elasticsearch)
            stores[domain] = (milvus, elasticsearch)
        return DomainRetrievalRuntime(
            embeddings=embeddings,
            catalog=RagCatalog(
                embeddings,
                stores,
                configs,
                RagConfig(
                    dense_top_k=settings.rag_top_k_dense,
                    bm25_top_k=settings.rag_top_k_bm25,
                    final_top_k=settings.rag_top_k_final,
                    min_score=settings.rag_min_score,
                ),
            ),
            milvus_stores=tuple(milvus_stores),
            elasticsearch_stores=tuple(elasticsearch_stores),
        )
    except Exception:
        for store in elasticsearch_stores:
            await store.aclose()
        for store in milvus_stores:
            await store.close()
        await embeddings.aclose()
        raise


class AMapWorkflowVerifier:
    _SCENIC_TYPE_CODE = "110000"
    _ATTRACTION_TYPE_HINTS = ("风景名胜", "公园", "博物馆", "纪念馆", "展览馆", "动物园", "植物园", "海滨", "海岛")

    def __init__(self, service: AMapService) -> None:
        self.service = service

    async def verify_poi(self, poi_id: str) -> VerifiedPoi:
        poi = await self.service.verify_poi(poi_id)
        if isinstance(poi, MapUnavailable):
            raise DependencyUnavailable("amap", poi.message)
        if poi.adcode is None:
            raise DependencyUnavailable("amap", "Verified POI did not include an administrative city code.")
        return VerifiedPoi(
            poi_id=poi.id,
            name=poi.name,
            city_code=poi.adcode,
            longitude=poi.location[0],
            latitude=poi.location[1],
        )

    async def discover_scenic_pois(self, city_code: str, limit: int = 10) -> list[VerifiedPoi]:
        """Search AMap directly for scenic/attraction POIs in a city."""
        if not self.service.api_key:
            raise DependencyUnavailable("amap", "AMap API key not configured.")
        pois = await self.service.search_pois("景点", city_code, types=self._SCENIC_TYPE_CODE)
        results: list[VerifiedPoi] = []
        for poi in pois[:limit]:
            if poi.adcode is None or not _city_code_matches(city_code, poi.adcode):
                continue
            if not self._is_attraction(poi.type_name):
                continue
            results.append(
                VerifiedPoi(
                    poi_id=poi.id,
                    name=poi.name,
                    city_code=poi.adcode,
                    longitude=poi.location[0],
                    latitude=poi.location[1],
                )
            )
        return results

    @classmethod
    def _is_attraction(cls, type_name: str | None) -> bool:
        return isinstance(type_name, str) and any(hint in type_name for hint in cls._ATTRACTION_TYPE_HINTS)


class ApprovedPoiCandidateRetriever:
    """Returns administrator-approved official POIs, freshly verified with AMap."""

    _ATTRACTION_TYPE_HINTS = ("风景名胜", "公园", "博物馆", "纪念馆", "展览馆", "动物园", "植物园", "海滨", "海岛")

    async def retrieve(self, request: GenerationRequest) -> tuple[VerifiedPlanningCandidate, ...]:
        async with SessionLocal() as session:
            candidates = list((await session.scalars(
                select(PoiCandidate)
                .where(PoiCandidate.city_code == request.city_code, PoiCandidate.status == "approved")
                .order_by(
                    PoiCandidate.admin_weight.desc(),
                    PoiCandidate.confirmed_itinerary_count.desc(),
                    PoiCandidate.discovery_count.desc(),
                    PoiCandidate.updated_at.desc(),
                    PoiCandidate.poi_id.asc(),
                )
                .limit(30)
            )).all())
            official_sources = list((await session.scalars(
                select(OfficialKnowledgeSource)
                .where(
                    OfficialKnowledgeSource.city_code == request.city_code,
                    OfficialKnowledgeSource.source_type == "poi",
                    OfficialKnowledgeSource.status == "indexed",
                    OfficialKnowledgeSource.poi_id.is_not(None),
                )
                .order_by(
                    OfficialKnowledgeSource.reviewed_at.desc(),
                    OfficialKnowledgeSource.updated_at.desc(),
                    OfficialKnowledgeSource.poi_id.asc(),
                )
                .limit(30)
            )).all())
        tags = set(request.preference_tags)
        if tags:
            candidates = [candidate for candidate in candidates if tags.intersection(candidate.tags)]
        maps = AMapService()
        verified: list[VerifiedPlanningCandidate] = []
        seen_poi_ids: set[str] = set()
        for candidate in candidates:
            poi = await maps.verify_poi(candidate.poi_id)
            if isinstance(poi, MapUnavailable) or poi.adcode is None:
                continue
            if not _city_code_matches(request.city_code, poi.adcode) or not self._is_attraction(poi.type_name):
                continue
            seen_poi_ids.add(poi.id)
            verified.append(VerifiedPlanningCandidate(
                poi_id=poi.id,
                poi_name=poi.name,
                city_code=poi.adcode,
                longitude=poi.location[0],
                latitude=poi.location[1],
                source=Citation(
                    document_id=f"approved-poi:{candidate.id}",
                    chunk_id=f"approved-poi:{candidate.id}",
                    source_type="approved_poi",
                    source_id=candidate.id,
                    city_code=request.city_code,
                    source_updated_at=candidate.updated_at.isoformat(),
                    content=f"管理员审核景点：{poi.name}。标签：{'、'.join(candidate.tags)}。",
                    poi_id=poi.id,
                ),
            ))
        for source in official_sources:
            if not source.poi_id or source.poi_id in seen_poi_ids:
                continue
            poi = await maps.verify_poi(source.poi_id)
            if isinstance(poi, MapUnavailable) or poi.adcode is None:
                continue
            if not _city_code_matches(request.city_code, poi.adcode) or not self._is_attraction(poi.type_name):
                continue
            seen_poi_ids.add(poi.id)
            verified.append(VerifiedPlanningCandidate(
                poi_id=poi.id,
                poi_name=poi.name,
                city_code=poi.adcode,
                longitude=poi.location[0],
                latitude=poi.location[1],
                source=Citation(
                    document_id=source.id,
                    chunk_id=f"official-poi:{source.id}",
                    source_type="official_poi",
                    source_id=source.id,
                    city_code=request.city_code,
                    source_updated_at=source.updated_at.isoformat(),
                    content=source.body_text,
                    poi_id=poi.id,
                ),
            ))
        return tuple(verified)

    @classmethod
    def _is_attraction(cls, type_name: str | None) -> bool:
        return isinstance(type_name, str) and any(hint in type_name for hint in cls._ATTRACTION_TYPE_HINTS)


def _city_code_matches(requested_city_code: str, poi_adcode: str) -> bool:
    if requested_city_code == poi_adcode:
        return True
    if len(requested_city_code) != 6 or len(poi_adcode) != 6 or not requested_city_code.endswith("00"):
        return False
    if requested_city_code[:4] == poi_adcode[:4]:
        return True
    return requested_city_code[:2] in {"11", "12", "31", "50"} and requested_city_code[:2] == poi_adcode[:2]


class ItineraryConstraints:
    async def check(self, request: GenerationRequest, draft: object) -> ConstraintCheck:
        total = sum(
            activity.activity.estimated_cost
            for day in getattr(draft, "days", ())
            for activity in day.activities
        )
        if request.budget_amount is not None and total > request.budget_amount:
            return ConstraintCheck(False, ("The preview exceeds the requested budget.",))
        return ConstraintCheck(True)


@dataclass
class AIRuntime:
    pool_factory: AsyncpgPoolFactory
    memory: AIMemoryRepository
    embeddings: OpenAICompatibleEmbeddingProvider
    milvus: ZillizMilvusDenseStore
    elasticsearch: ElasticsearchAsyncBm25Store
    generator: DashScopeStructuredDraftGenerator
    workflow_factory: LangGraphWorkflowFactory
    exit_stack: AsyncExitStack
    domain_retrieval: DomainRetrievalRuntime

    async def close(self) -> None:
        await self.domain_retrieval.close()
        await self.embeddings.aclose()
        await self.milvus.close()
        await self.elasticsearch.aclose()
        await self.generator.aclose()
        await self.exit_stack.aclose()
        await self.pool_factory.close()

    def dependencies(self) -> GenerationDependencies:
        settings = Settings()
        web_search = UnavailableWebSearchProvider()
        if (
            settings.magic_mcp_websearch_url
            and settings.magic_mcp_websearch_tool
            and settings.magic_mcp_api_key
        ):
            client = httpx.AsyncClient(timeout=settings.magic_mcp_timeout_seconds)
            if hasattr(self, "exit_stack"):
                self.exit_stack.push_async_callback(client.aclose)
            web_search = MagicMcpWebSearchProvider(
                endpoint=settings.magic_mcp_websearch_url,
                tool=settings.magic_mcp_websearch_tool,
                api_key=settings.magic_mcp_api_key,
                timeout=settings.magic_mcp_timeout_seconds,
                client=client,
            )
        return GenerationDependencies(
            profile_memory=PrivateMemoryProfileLoader(self.memory, self.domain_retrieval.catalog),
            rag_retriever=DomainRagRetriever(self.domain_retrieval.catalog),
            draft_generator=self.generator,
            amap_verifier=AMapWorkflowVerifier(AMapService()),
            constraint_checker=ItineraryConstraints(),
            preview_store=self.memory,
            live_source_retriever=LiveSourceRetriever(web_search),
            live_source_resolver=LiveSourceResolver(AMapService()),
            approved_candidate_retriever=ApprovedPoiCandidateRetriever(),
        )

    def ingestion_service(self) -> KnowledgeIngestionService:
        return KnowledgeIngestionService(self.embeddings, self.milvus, self.elasticsearch)

    async def delete_knowledge_document(self, document_id: str) -> None:
        await self.milvus.delete_document(document_id)
        await self.elasticsearch.delete_document(document_id)


async def open_ai_runtime(settings: Settings) -> AIRuntime:
    # ① 检查 AI 是否启用
    if not settings.ai_enabled:
        raise DependencyUnavailable("ai", "AI planning is not enabled for this environment.")
    # ② 打开 AI PostgreSQL 连接池
    pool_factory = AsyncpgPoolFactory(settings.ai_postgres_dsn or "")
    pool = await pool_factory.open()
    memory = AIMemoryRepository(pool)
    exit_stack = AsyncExitStack()
    try:
        # ③ 初始化 AI 表结构
        await memory.setup_schema()
        # ④ 创建 LangGraph checkpoint 存储
        checkpointer = await exit_stack.enter_async_context(
            open_langgraph_checkpointer(settings.ai_postgres_dsn or "")
        )
        # ⑤ 初始化 Embedding Provider
        embeddings = OpenAICompatibleEmbeddingProvider(
            api_key=settings.embedding_api_key or settings.dashscope_api_key,
            base_url=settings.embedding_base_url or "",
            model=settings.embedding_model or "",
            dimensions=settings.embedding_dimensions,
            timeout=settings.embedding_timeout_seconds,
        )
        # ⑥ 初始化 Milvus 向量存储
        milvus = ZillizMilvusDenseStore(
            uri=settings.milvus_uri or "",
            token=settings.milvus_token or "",
            collection_name=settings.milvus_collection_travel_knowledge,
            dimensions=settings.embedding_dimensions,
        )
        # ⑦ 初始化 Elasticsearch BM25 存储
        elasticsearch = ElasticsearchAsyncBm25Store(
            hosts=settings.elasticsearch_url,
            index_name="travel_knowledge_v1",
        )
        await milvus.ensure_collection()
        await elasticsearch.ensure_index()
        # ⑧ 分域 RAG catalog
        domain_runtime = await open_domain_retrieval_runtime(settings)
        # ⑧b 组装 planning_agent 节点的生成器：默认 agent 循环，可回退单次调用
        if settings.planning_agent_mode == "single":
            generator: DashScopeStructuredDraftGenerator | AgentStructuredDraftGenerator = (
                DashScopeStructuredDraftGenerator(
                    api_key=settings.dashscope_api_key or "",
                    base_url=settings.llm_base_url or "",
                    model=settings.llm_model or "",
                    timeout=settings.llm_timeout_seconds,
                    retries=settings.llm_max_retries,
                )
            )
        else:
            generator = AgentStructuredDraftGenerator(
                api_key=settings.dashscope_api_key or "",
                base_url=settings.llm_base_url or "",
                model=settings.llm_model or "",
                timeout=settings.llm_timeout_seconds,
                retries=settings.llm_max_retries,
                settings=settings,
                catalog=domain_runtime.catalog,
            )
        # ⑨ 组装并返回完整运行时对象
        return AIRuntime(
            pool_factory=pool_factory,
            memory=memory,
            embeddings=embeddings,
            milvus=milvus,
            elasticsearch=elasticsearch,
            generator=generator,
            workflow_factory=LangGraphWorkflowFactory(checkpointer=checkpointer),
            exit_stack=exit_stack,
            domain_retrieval=domain_runtime,
        )
    except Exception:
        await exit_stack.aclose()
        await pool_factory.close()
        raise
