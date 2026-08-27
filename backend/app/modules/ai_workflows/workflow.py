from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import date
from time import perf_counter
from typing import Mapping, Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from app.modules.ai_agents.contracts import (
    AgentContext,
    GenerationReviewRequest,
    MapPoint,
    MapRouteRequest,
    MemoryRecord,
    MemoryRetrievalRequest,
    PlannedDay,
    PlannedItinerary,
    PlannedStop,
    PlanningCandidate,
    PlanningRequest,
    RetrievalDocument,
    RetrievalRequest,
)
from app.modules.ai_agents.services import (
    ControlledMapService,
    ControlledMemoryRetrievalService,
    ControlledRetrievalService,
    GenerationReviewService,
)
from app.modules.ai_workflows.contracts import (
    AMapPoiVerifier,
    ApprovedPlanningCandidateRetriever,
    Citation,
    ConstraintCheck,
    DraftActivity,
    DraftDay,
    GenerationRequest,
    ItineraryConstraintChecker,
    ItineraryDraft,
    NodeAudit,
    PreviewStore,
    ProfileMemoryLoader,
    ProgressCallback,
    RAGRetriever,
    SavedPreview,
    StructuredDraftGenerator,
    LiveSourceResolver,
    LiveSourceRetriever,
    VerifiedPlanningCandidate,
    VerifiedActivity,
    VerifiedDay,
    VerifiedItineraryDraft,
)


WORKFLOW_NODES = (
    "validate_request",
    "memory_retrieval_agent",
    "retrieval_agent",
    "planning_agent",
    "validate_schema",
    "map_agent",
    "generation_review_agent",
    "save_immutable_preview_with_audit",
    "user_confirmation",
)

_GRAPH_PROGRESS_CALLBACK: ContextVar[ProgressCallback | None] = ContextVar(
    "graph_progress_callback", default=None
)


class WorkflowError(RuntimeError):
    code = "WORKFLOW_ERROR"


class DependencyUnavailable(WorkflowError):
    code = "DEPENDENCY_UNAVAILABLE"

    def __init__(self, dependency: str, message: str | None = None) -> None:
        self.dependency = dependency
        super().__init__(message or f"Required dependency is unavailable: {dependency}")


class RequestValidationError(WorkflowError):
    code = "INVALID_REQUEST"


class DraftSchemaError(WorkflowError):
    code = "INVALID_DRAFT_SCHEMA"


class ConstraintViolation(WorkflowError):
    code = "CONSTRAINT_VIOLATION"

    def __init__(self, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__("Draft violates itinerary constraints: " + "; ".join(violations))


class InsufficientVerifiedCandidates(WorkflowError):
    code = "INSUFFICIENT_VERIFIED_CANDIDATES"
    message = "Not enough verified places were found for this trip."

    def __init__(self) -> None:
        super().__init__(self.message)


@dataclass(frozen=True)
class ReviewDecision:
    retry_planning: bool

#"依赖清单/配置单"
@dataclass(frozen=True)
class GenerationDependencies:
    profile_memory: ProfileMemoryLoader
    rag_retriever: RAGRetriever
    draft_generator: StructuredDraftGenerator
    amap_verifier: AMapPoiVerifier
    constraint_checker: ItineraryConstraintChecker
    preview_store: PreviewStore
    live_source_retriever: LiveSourceRetriever | None = None
    live_source_resolver: LiveSourceResolver | None = None
    approved_candidate_retriever: ApprovedPlanningCandidateRetriever | None = None


@dataclass
class WorkflowState:
    request: GenerationRequest
    current_node: str = "validate_request"
    profile_memory: Mapping[str, object] | None = None
    citations: tuple[Citation, ...] = ()
    verified_candidates: tuple[VerifiedPlanningCandidate, ...] = ()
    live_source_used: bool = False
    generated_draft: Mapping[str, object] | None = None
    draft: ItineraryDraft | None = None
    verified_draft: VerifiedItineraryDraft | None = None
    constraint_check: ConstraintCheck | None = None
    review_decision: ReviewDecision | None = None
    revision_count: int = 0
    preview: SavedPreview | None = None
    confirmation_required: bool = False
    audit: list[NodeAudit] = field(default_factory=list)

    def complete(self, node: str) -> None:
        self.current_node = node
        self.audit.append(NodeAudit(node=node, status="completed"))

#给"工作流"定一个统一接口规定
class GenerationWorkflow(Protocol):
    async def run(self, request: GenerationRequest) -> WorkflowState: ...


class WorkflowFactory(Protocol):
    def create(self, dependencies: GenerationDependencies) -> GenerationWorkflow: ...


class LocalWorkflowFactory:
    """Deterministic implementation used until an integration supplies LangGraph.

    This is deliberately a separate factory so a LangGraph-backed factory can
    be introduced without changing worker or API callers. The project does not
    declare LangGraph today, and this module never emulates that package.
    """

    def create(self, dependencies: GenerationDependencies) -> "LocalGenerationWorkflow":
        return LocalGenerationWorkflow(dependencies)


class LocalGenerationWorkflow:
    def __init__(self, dependencies: GenerationDependencies) -> None:
        self.dependencies = dependencies

    async def run(self, request: GenerationRequest) -> WorkflowState:
        state = WorkflowState(request=request)
        self._validate_request(state)
        await asyncio.gather(self._load_profile_memory(state), self._retrieve_rag_context(state))
        await self._prepare_verified_candidates(state)
        while True:
            await self._generate_structured_draft(state)
            await _report_progress(state.request, "validating")
            self._validate_schema(state)
            await self._verify_pois_with_amap(state)
            decision = await self._check_date_budget_route_constraints(state)
            if not decision.retry_planning:
                break
        await self._save_preview_with_citations(state)
        self._user_confirmation(state)
        return state
    #node 1 图包装：workflow.py:517-528（_graph_validate_request）→ 核心：workflow.py:196-207（_validate_request）
    @staticmethod
    def _validate_request(state: WorkflowState) -> None:
        request = state.request
        if not request.generation_job_id or not request.user_id or not request.prompt.strip():
            raise RequestValidationError("generation_job_id, user_id, and prompt are required")
        if not request.city_code:
            raise RequestValidationError("city_code is required")
        duration = (request.end_date - request.start_date).days + 1
        if not 1 <= duration <= 7:
            raise RequestValidationError("An itinerary must span one to seven days")
        if request.budget_amount is not None and request.budget_amount < 0:
            raise RequestValidationError("budget_amount cannot be negative")
        state.complete("validate_request")
    #node 2 图包装 从 PG 读用户旅行档案
    async def _load_profile_memory(self, state: WorkflowState) -> None:
        state.profile_memory = await self.dependencies.profile_memory.load_profile_memory(state.request.user_id)
        state.complete("memory_retrieval_agent")

    async def _retrieve_rag_context(self, state: WorkflowState) -> None:
        citations = await self.dependencies.rag_retriever.retrieve(state.request)
        if any(citation.city_code != state.request.city_code for citation in citations):
            raise DraftSchemaError("RAG citations must match the request city")
        state.citations = citations
        state.complete("retrieval_agent")
    #node 3 图包装：workflow.py:598-610（_graph_generate_structured_draft）→ 核心：workflow.py:220-229
    async def _generate_structured_draft(self, state: WorkflowState) -> None:
        if state.profile_memory is None:
            raise DependencyUnavailable("profile_memory")
        await _report_progress(state.request, "planning")
        request = replace(state.request, verified_candidates=state.verified_candidates)
        generated_draft = await self.dependencies.draft_generator.generate(
            request, state.profile_memory, state.citations
        )
        state.generated_draft = _merge_target_snapshot(state.request, generated_draft)
        state.complete("planning_agent")
    #node 4 图包装：workflow.py:612-624 → 核心：workflow.py:231-293（_validate_schema）强校验
    @staticmethod
    def _validate_schema(state: WorkflowState) -> None:
        raw = state.generated_draft
        if raw is None:
            raise DraftSchemaError("Generator did not return a draft")
        title = raw.get("title")
        days = raw.get("days")
        if not isinstance(title, str) or not title.strip() or not isinstance(days, list):
            raise DraftSchemaError("Draft requires a title and days array")
        expected_dates = tuple(
            state.request.start_date.fromordinal(state.request.start_date.toordinal() + offset)
            for offset in range((state.request.end_date - state.request.start_date).days + 1)
        )
        if len(days) != len(expected_dates):
            raise DraftSchemaError("Draft must contain one day for every requested travel date")
        parsed_days: list[DraftDay] = []
        for item in days:
            if not isinstance(item, Mapping) or not isinstance(item.get("date"), str) or not isinstance(item.get("activities"), list):
                raise DraftSchemaError("Each day requires date and activities")
            try:
                day_date = date.fromisoformat(item["date"])
            except ValueError as error:
                raise DraftSchemaError("Day date must be ISO-8601") from error
            if day_date not in expected_dates:
                raise DraftSchemaError("Draft day dates must stay within the requested travel dates")
            if (
                len(item["activities"]) < 2
                and state.request.target_itinerary_id is None
                and not _is_unchanged_empty_target_day(state.request, day_date)
            ):
                raise InsufficientVerifiedCandidates()
            if len(item["activities"]) > 3:
                raise DraftSchemaError("Each draft day may contain at most three activities")
            activities: list[DraftActivity] = []
            for activity in item["activities"]:
                if not isinstance(activity, Mapping):
                    raise DraftSchemaError("Each activity must be an object")
                poi_id, activity_title, estimated_cost = activity.get("poi_id"), activity.get("title"), activity.get("estimated_cost", 0)
                if not isinstance(poi_id, str) or not poi_id or not isinstance(activity_title, str) or not activity_title:
                    raise DraftSchemaError("Each activity requires poi_id and title")
                normalized_cost = _normalize_estimated_cost(estimated_cost)
                if normalized_cost is None:
                    raise DraftSchemaError("estimated_cost must be a non-negative integer")
                event_id = activity.get("event_id")
                if event_id is not None and (not isinstance(event_id, str) or not event_id):
                    raise DraftSchemaError("event_id must be a non-empty string when provided")
                activities.append(DraftActivity(poi_id, activity_title, normalized_cost, event_id))
            parsed_days.append(DraftDay(day_date, tuple(activities)))
        if tuple(day.day_date for day in parsed_days) != expected_dates:
            raise DraftSchemaError("Draft days must cover requested travel dates in order")
        if state.request.target_itinerary_id is None:
            allowed = {candidate.poi_id: candidate.poi_name for candidate in state.verified_candidates}
            selected = [activity for day in parsed_days for activity in day.activities]
            if any(allowed.get(activity.poi_id) != activity.title for activity in selected):
                raise DraftSchemaError("Draft activities must use verified candidate POI IDs and titles")
            if len({activity.poi_id for activity in selected}) != len(selected):
                raise DraftSchemaError("Draft activities must not repeat a POI")
            selected_poi_ids = {activity.poi_id for activity in selected}
            missing_must_visit = set(state.request.must_visit_poi_ids) - selected_poi_ids
            if missing_must_visit:
                raise DraftSchemaError("Draft must include every selected must-visit POI")
        state.draft = ItineraryDraft(title.strip(), tuple(parsed_days))
        state.complete("validate_schema")
    #node 5 图包装：workflow.py:626-641 → 核心：workflow.py:295-308（_verify_pois_with_amap）
    async def _verify_pois_with_amap(self, state: WorkflowState) -> None:
        if state.draft is None:
            raise DraftSchemaError("Draft schema has not been validated")
        verified_days: list[VerifiedDay] = []
        for day in state.draft.days:
            activities: list[VerifiedActivity] = []
            for activity in day.activities:
                poi = await self.dependencies.amap_verifier.verify_poi(activity.poi_id)
                if not _city_code_matches(state.request.city_code, poi.city_code):
                    raise DraftSchemaError(f"POI {activity.poi_id} is not in the requested city")
                activities.append(VerifiedActivity(activity, poi))
            verified_days.append(VerifiedDay(day.day_date, tuple(activities)))
        state.verified_draft = VerifiedItineraryDraft(state.draft.title, tuple(verified_days))
        state.complete("map_agent")
#合并"必去 POI + 管理员审核 POI + RAG/官方 POI 源 → 不足则高德直搜景点 → 仍不足则联网攻略兜底"
    #候选池必须 ≥ 2×天数 个经高德验证的POI。POI发现归高德（地图是POI的权威来源），
    #联网搜索只负责找攻略/时效信息，不负责猜POI名字。
    async def _prepare_verified_candidates(self, state: WorkflowState) -> None:
        if state.request.target_itinerary_id is not None:
            return
        required = 2 * ((state.request.end_date - state.request.start_date).days + 1)
        await _report_progress(state.request, "retrieving_reviewed_sources")
        verified = list(await self._must_visit_candidates(state))
        verified.extend(
            candidate
            for candidate in await self._approved_candidates(state)
            if candidate.poi_id not in {item.poi_id for item in verified}
        )
        state.citations += tuple(candidate.source for candidate in verified)
        known = {candidate.poi_id for candidate in verified}
        verified.extend(candidate for candidate in await self._reviewed_candidates(state) if candidate.poi_id not in known)
        if len(verified) < required:
            try:
                scenic_pois = await self.dependencies.amap_verifier.discover_scenic_pois(
                    state.request.city_code, limit=required - len(verified) + 5
                )
                for poi in scenic_pois:
                    if poi.poi_id in known:
                        continue
                    known.add(poi.poi_id)
                    source = Citation(
                        document_id=f"amap-scenic-{poi.poi_id}",
                        chunk_id=f"amap-scenic-{poi.poi_id}",
                        source_type="amap_scenic",
                        source_id=poi.poi_id,
                        city_code=poi.city_code,
                        source_updated_at="",
                        content=f"AMap-discovered scenic POI: {poi.name}.",
                        poi_id=poi.poi_id,
                    )
                    verified.append(
                        VerifiedPlanningCandidate(
                            poi.poi_id, poi.name, poi.city_code, poi.longitude, poi.latitude, source
                        )
                    )
                    state.citations += (source,)
            except DependencyUnavailable:
                pass
        if len(verified) < required:
            retriever = self.dependencies.live_source_retriever
            resolver = self.dependencies.live_source_resolver
            if retriever is not None and resolver is not None:
                try:
                    await _report_progress(state.request, "searching_live_sources")
                    sources = await retriever.retrieve(state.request)
                    live_candidates = await resolver.resolve(state.request, sources)
                except DependencyUnavailable:
                    raise
                except Exception:
                    live_candidates = ()
                state.live_source_used = bool(live_candidates)
                known = {candidate.poi_id for candidate in verified}
                verified.extend(candidate for candidate in live_candidates if candidate.poi_id not in known)
                existing_chunk_ids = {citation.chunk_id for citation in state.citations}
                state.citations += tuple(
                    candidate.source
                    for candidate in live_candidates
                    if candidate.source.chunk_id not in existing_chunk_ids
                )
        if len(verified) < required:
            raise InsufficientVerifiedCandidates()
        await _report_progress(state.request, "verifying_pois")
        state.verified_candidates = tuple(verified)

    async def _must_visit_candidates(self, state: WorkflowState) -> tuple[VerifiedPlanningCandidate, ...]:
        candidates: list[VerifiedPlanningCandidate] = []
        for poi_id in dict.fromkeys(state.request.must_visit_poi_ids):
            try:
                poi = await self.dependencies.amap_verifier.verify_poi(poi_id)
            except DependencyUnavailable:
                raise RequestValidationError(
                    "MUST_VISIT_POI_UNAVAILABLE",
                    f"必去景点无法验证，请重新选择：{poi_id}",
                )
            if not _city_code_matches(state.request.city_code, poi.city_code):
                raise DraftSchemaError(f"Must-visit POI {poi_id} is not in the requested city")
            candidates.append(
                VerifiedPlanningCandidate(
                    poi_id=poi.poi_id,
                    poi_name=poi.name,
                    city_code=poi.city_code,
                    longitude=poi.longitude,
                    latitude=poi.latitude,
                    source=Citation(
                        document_id=f"requested-poi:{poi.poi_id}",
                        chunk_id=f"requested-poi:{poi.poi_id}",
                        source_type="requested_poi",
                        source_id=poi.poi_id,
                        city_code=state.request.city_code,
                        source_updated_at="",
                        content=f"User-selected, AMap-verified POI: {poi.name}.",
                        poi_id=poi.poi_id,
                    ),
                )
            )
        return tuple(candidates)

    async def _approved_candidates(self, state: WorkflowState) -> tuple[VerifiedPlanningCandidate, ...]:
        retriever = self.dependencies.approved_candidate_retriever
        return await retriever.retrieve(state.request) if retriever is not None else ()

    async def _reviewed_candidates(self, state: WorkflowState) -> list[VerifiedPlanningCandidate]:
        verified: list[VerifiedPlanningCandidate] = []
        seen_poi_ids: set[str] = set()
        for citation in state.citations:
            if not citation.poi_id or citation.poi_id in seen_poi_ids:
                continue
            try:
                poi = await self.dependencies.amap_verifier.verify_poi(citation.poi_id)
            except DependencyUnavailable:
                continue
            if not _city_code_matches(state.request.city_code, poi.city_code):
                continue
            seen_poi_ids.add(poi.poi_id)
            verified.append(
                VerifiedPlanningCandidate(
                    poi.poi_id, poi.name, poi.city_code, poi.longitude, poi.latitude, citation
                )
            )
        return verified
    # node 6 图包装：workflow.py:643-662 → 核心：workflow.py:400-420（约束+决定）+ services.py:121-148（受控审查）
    async def _check_date_budget_route_constraints(self, state: WorkflowState) -> ReviewDecision:
        if state.verified_draft is None:
            raise DependencyUnavailable("amap_verifier")
        check = await self.dependencies.constraint_checker.check(state.request, state.verified_draft)
        state.constraint_check = check
        if check.passed:
            decision = ReviewDecision(retry_planning=False)
            outcome = f"passed_after_{state.revision_count}_revisions"
        elif state.revision_count < 2:
            state.revision_count += 1
            decision = ReviewDecision(retry_planning=True)
            outcome = f"revision_{state.revision_count}_requested"
        else:
            decision = ReviewDecision(retry_planning=False)
            outcome = f"terminal_after_{state.revision_count}_revisions"
        state.review_decision = decision
        state.current_node = "generation_review_agent"
        state.audit.append(NodeAudit(node="generation_review_agent", status=outcome))
        if not check.passed and not decision.retry_planning:
            raise ConstraintViolation(check.violations)
        return decision

    async def _save_preview_with_citations(self, state: WorkflowState) -> None:
        if state.verified_draft is None:
            raise DraftSchemaError("POIs have not been verified")
        preview = await self.dependencies.preview_store.save_preview(
            state.request, state.verified_draft, state.citations, tuple(state.audit)
        )
        if not preview.preview_id:
            raise DependencyUnavailable("preview_store", "Preview store did not return a preview ID")
        state.preview = preview
        state.complete("save_immutable_preview_with_audit")
    # node 8 图包装：workflow.py:703-714 → 核心：workflow.py:433-436（_user_confirmation）
    @staticmethod
    def _user_confirmation(state: WorkflowState) -> None:
        state.confirmation_required = True
        state.complete("user_confirmation")


class _LangGraphState(TypedDict):
    workflow_state: WorkflowState


class LangGraphWorkflowFactory:
    """Build the production StateGraph while leaving dependency wiring to callers."""

    def __init__(self, checkpointer: object | None = None) -> None:
        self.checkpointer = checkpointer

    def create(self, dependencies: GenerationDependencies) -> "LangGraphGenerationWorkflow":
        return LangGraphGenerationWorkflow(dependencies, checkpointer=self.checkpointer)


class LangGraphGenerationWorkflow(LocalGenerationWorkflow):
    """StateGraph-backed preview generation workflow.

    Nodes share the same mutable WorkflowState to retain the complete audit
    trail. Exceptions are intentionally not translated by LangGraph nodes, so
    callers receive the workflow's typed errors unchanged.
    """

    def __init__(self, dependencies: GenerationDependencies, *, checkpointer: object | None = None) -> None:
        super().__init__(dependencies)
        self.memory_retrieval = ControlledMemoryRetrievalService()
        self.retrieval = ControlledRetrievalService()
        self.map_routing = ControlledMapService()
        self.review = GenerationReviewService()
        self.checkpointer = checkpointer
        graph = StateGraph(_LangGraphState)
        graph.add_node("validate_request", self._graph_validate_request)
        graph.add_node("retrieve_evidence", self._graph_retrieve_evidence)
        graph.add_node("planning_agent", self._graph_generate_structured_draft)
        graph.add_node("validate_schema", self._graph_validate_schema)
        graph.add_node("map_agent", self._graph_verify_pois_with_amap)
        graph.add_node(
            "generation_review_agent", self._graph_check_date_budget_route_constraints
        )
        graph.add_node("save_immutable_preview_with_audit", self._graph_save_preview_with_citations)
        graph.add_node("user_confirmation", self._graph_user_confirmation)
        graph.add_edge(START, "validate_request")
        graph.add_edge("validate_request", "retrieve_evidence")
        graph.add_edge("retrieve_evidence", "planning_agent")
        graph.add_edge("planning_agent", "validate_schema")
        graph.add_edge("validate_schema", "map_agent")
        graph.add_edge("map_agent", "generation_review_agent")
        graph.add_conditional_edges(
            "generation_review_agent",
            self._route_review,
            {
                "planning_agent": "planning_agent",
                "save_immutable_preview_with_audit": "save_immutable_preview_with_audit",
            },
        )
        graph.add_edge("save_immutable_preview_with_audit", "user_confirmation")
        graph.add_edge("user_confirmation", END)
        self.graph = graph.compile(checkpointer=checkpointer)

    async def run(self, request: GenerationRequest) -> WorkflowState:
        callback_token = _GRAPH_PROGRESS_CALLBACK.set(request.progress_callback)
        checkpoint_request = replace(request, progress_callback=None)
        try:
            result = await self.graph.ainvoke(
                {"workflow_state": WorkflowState(request=checkpoint_request)},
                config={
                    "configurable": {
                        "thread_id": request.workflow_run_id or request.generation_job_id,
                    }
                },
            )
            return result["workflow_state"]
        finally:
            _GRAPH_PROGRESS_CALLBACK.reset(callback_token)

    @staticmethod
    def _state(state: _LangGraphState) -> WorkflowState:
        return state["workflow_state"]
    #node 1 · validate_request确定性校验，不碰外部
    async def _graph_validate_request(self, graph_state: _LangGraphState) -> _LangGraphState:
        state = self._state(graph_state)
        started_at = perf_counter()
        self._validate_request(state)
        _record_production_audit(
            state,
            "validate_request",
            started_at,
            agent_version="workflow@1",
            tool_summary={"validation": "completed"},
        )
        return graph_state
    #node 2 · retrieve_evidence记忆 + 公共知识，一步投喂后续的证据底座
    async def _graph_retrieve_evidence(self, graph_state: _LangGraphState) -> _LangGraphState:
        state = self._state(graph_state)
        await _report_progress(state.request, "retrieving")
        memory_started_at = perf_counter()
        await self._load_profile_memory(state)
        profile = state.profile_memory
        records = _memory_records_from_profile(profile, state.request.user_id)
        memory_result = self.memory_retrieval.retrieve(
            MemoryRetrievalRequest(
                context=AgentContext(user_id=state.request.user_id, city_code=state.request.city_code),
                query=state.request.prompt,
            ),
            records,
        )
        state.profile_memory = _profile_from_memory_records(memory_result.records)
        _record_production_audit(
            state,
            "memory_retrieval_agent",
            memory_started_at,
            agent_version="controlled-memory-retrieval@1",
            redacted_summary="Filtered owner-scoped profile memory.",
            tool_summary={"loaded": len(records), "selected": len(memory_result.records)},
            degradations=("memory_untyped_ignored",) if profile and not records else (),
        )
        #公共知识
        retrieval_started_at = perf_counter()
        # 来源引用
        citations = await self.dependencies.rag_retriever.retrieve(state.request)
        documents = tuple(_retrieval_document(citation) for citation in citations)
        if not documents:
            state.citations = ()
            await self._prepare_verified_candidates(state)
            state.complete("retrieval_agent")
            _record_production_audit(
                state,
                "retrieval_agent",
                retrieval_started_at,
                agent_version="controlled-retrieval@1",
                redacted_summary="No reviewed evidence was available; preparing bounded live fallback.",
                tool_summary={"loaded": 0, "selected": 0},
            )
            return graph_state
        retrieval_result = self.retrieval.retrieve(
            RetrievalRequest(
                context=AgentContext(user_id=state.request.user_id, city_code=state.request.city_code),
                query=state.request.prompt,
            ),
            documents,
        )
        selected_chunk_ids = {document.chunk_id for document in retrieval_result.documents}
        state.citations = tuple(
            citation
            for citation in citations
            if citation.chunk_id in selected_chunk_ids
        )
        await self._prepare_verified_candidates(state)
        state.complete("retrieval_agent")
        _record_production_audit(
            state,
            "retrieval_agent",
            retrieval_started_at,
            agent_version="controlled-retrieval@1",
            redacted_summary="Filtered source citations to the requested city.",
            tool_summary={"loaded": len(documents), "selected": len(retrieval_result.documents)},
            degradations=("foreign_city_citations_filtered",) if len(documents) != len(retrieval_result.documents) else (),
        )
        return graph_state
    #node 3 · planning_agent全流程唯一一次 LLM 调用
    async def _graph_generate_structured_draft(self, graph_state: _LangGraphState) -> _LangGraphState:
        state = self._state(graph_state)
        started_at = perf_counter()
        await self._generate_structured_draft(state)
        _record_production_audit(
            state,
            "planning_agent",
            started_at,
            agent_version="llm-draft-generator@1",
            redacted_summary="Generated a structured itinerary draft.",
            tool_summary={"citations": len(state.citations)},
        )
        return graph_state
    #node 4 · validate_schema把"合法的 JSON"变成"可用的业务对象"
    async def _graph_validate_schema(self, graph_state: _LangGraphState) -> _LangGraphState:
        state = self._state(graph_state)
        started_at = perf_counter()
        await _report_progress(state.request, "validating")
        self._validate_schema(state)
        _record_production_audit(
            state,
            "validate_schema",
            started_at,
            agent_version="workflow@1",
            tool_summary={"days": len(state.draft.days) if state.draft else 0},
        )
        return graph_state
    #node 5 · map_agent高德二次核验，给每个 POI 打坐标
    async def _graph_verify_pois_with_amap(self, graph_state: _LangGraphState) -> _LangGraphState:
        state = self._state(graph_state)
        started_at = perf_counter()
        await self._verify_pois_with_amap(state)
        _record_production_audit(
            state,
            "map_agent",
            started_at,
            agent_version="amap-verifier@1",
            tool_summary={
                "verified_pois": sum(len(day.activities) for day in state.verified_draft.days)
                if state.verified_draft
                else 0
            },
        )
        return graph_state
    #node 6 · generation_review_agent唯一的分流点：通过则保存，否则重规划（≤2 次）
    async def _graph_check_date_budget_route_constraints(
        self, graph_state: _LangGraphState
    ) -> _LangGraphState:
        state = self._state(graph_state)
        started_at = perf_counter()
        await self._check_date_budget_route_constraints(state)
        review_result = self.review.review(_controlled_review_request(state))
        review_codes = tuple(issue.code for issue in review_result.issues)
        if not review_result.approved:
            if state.revision_count < 2:
                state.revision_count += 1
                state.review_decision = ReviewDecision(retry_planning=True)
                _record_production_audit(
                    state,
                    "generation_review_agent",
                    started_at,
                    agent_version="controlled-generation-review@1",
                    redacted_summary="Review found issues; requesting a planning retry.",
                    tool_summary={"issues": len(review_codes)},
                    review_codes=review_codes,
                )
                return graph_state
            raise ConstraintViolation(review_codes)
        _record_production_audit(
            state,
            "generation_review_agent",
            started_at,
            agent_version="controlled-generation-review@1",
            redacted_summary="Checked itinerary constraints, evidence, and route consistency.",
            tool_summary={"issues": len(review_codes)},
            review_codes=review_codes,
        )
        return graph_state

    @staticmethod
    def _route_review(graph_state: _LangGraphState) -> str:
        decision = graph_state["workflow_state"].review_decision
        if decision is None:
            raise RuntimeError("Generation review did not produce a decision")
        if decision.retry_planning:
            return "planning_agent"
        return "save_immutable_preview_with_audit"
    #node 7 · save_immutable_preview_with_audit不可变快照落库，附带完整审计链
    async def _graph_save_preview_with_citations(self, graph_state: _LangGraphState) -> _LangGraphState:
        state = self._state(graph_state)
        started_at = perf_counter()
        if state.verified_draft is None:
            raise DraftSchemaError("POIs have not been verified")
        state.current_node = "save_immutable_preview_with_audit"
        state.audit.append(
            NodeAudit(
                node="save_immutable_preview_with_audit",
                status="completed",
                agent_version="preview-store@1",
                duration_ms=0,
                tool_summary={"citations": len(state.citations)},
            )
        )
        preview = await self.dependencies.preview_store.save_preview(
            state.request, state.verified_draft, state.citations, tuple(state.audit)
        )
        if not preview.preview_id:
            raise DependencyUnavailable("preview_store", "Preview store did not return a preview ID")
        state.preview = preview
        _record_production_audit(
            state,
            "save_immutable_preview_with_audit",
            started_at,
            agent_version="preview-store@1",
            tool_summary={"citations": len(state.citations)},
        )
        return graph_state
    #node 8 · user_confirmationHITL 停止线：到此图任务完成，但什么都不写正式行程
    async def _graph_user_confirmation(self, graph_state: _LangGraphState) -> _LangGraphState:
        state = self._state(graph_state)
        started_at = perf_counter()
        self._user_confirmation(state)
        _record_production_audit(
            state,
            "user_confirmation",
            started_at,
            agent_version="workflow@1",
            tool_summary={"confirmation_required": True},
        )
        return graph_state

#只取 owner 明确的字符串偏好
def _memory_records_from_profile(
    profile_memory: Mapping[str, object] | None, user_id: str
) -> tuple[MemoryRecord, ...]:
    """Adapt only explicitly owner-scoped string preferences to typed records."""
    if not isinstance(profile_memory, Mapping):
        return ()
    declared_user_id = profile_memory.get("user_id")
    if declared_user_id is not None and declared_user_id != user_id:
        return ()
    records: list[MemoryRecord] = []
    for index, (key, value) in enumerate(sorted(profile_memory.items())):
        if key == "user_id" or not isinstance(key, str):
            continue
        if isinstance(value, str):
            serialized_value = value
        elif isinstance(value, Mapping):
            serialized_value = json.dumps(value, sort_keys=True, ensure_ascii=True)
        else:
            continue
        try:
            records.append(
                MemoryRecord(
                    memory_id=f"profile-{index}",
                    user_id=user_id,
                    key=key,
                    value=serialized_value,
                    confidence=1,
                )
            )
        except ValueError:
            continue
    return tuple(records)


async def _report_progress(request: GenerationRequest, phase: str) -> None:
    callback = request.progress_callback or _GRAPH_PROGRESS_CALLBACK.get()
    if callback is not None:
        await callback(phase)


def _merge_target_snapshot(
    request: GenerationRequest, generated: Mapping[str, object]
) -> Mapping[str, object]:
    """Keep days omitted by a modification response unchanged in its preview."""
    if request.target_itinerary_id is None or not isinstance(request.base_snapshot, Mapping):
        return generated
    generated_days = generated.get("days")
    base_days = request.base_snapshot.get("days")
    if not isinstance(generated_days, list) or not isinstance(base_days, list):
        return generated
    merged_days = {
        item.get("date"): item
        for item in generated_days
        if isinstance(item, Mapping) and isinstance(item.get("date"), str)
    }
    for base_day in base_days:
        if not isinstance(base_day, Mapping):
            continue
        day_date = base_day.get("day_date")
        events = base_day.get("events")
        if not isinstance(day_date, str) or day_date in merged_days or not isinstance(events, list):
            continue
        activities = []
        for event in events:
            if not isinstance(event, Mapping):
                continue
            poi_snapshot = event.get("poi_snapshot")
            location = poi_snapshot.get("location") if isinstance(poi_snapshot, Mapping) else None
            if not isinstance(location, Mapping):
                continue
            poi_id = event.get("poi_id")
            poi_name = poi_snapshot.get("name") if isinstance(poi_snapshot, Mapping) else None
            if not isinstance(poi_id, str) or not isinstance(poi_name, str):
                continue
            activities.append({
                "poi_id": poi_id,
                "title": event.get("notes") if isinstance(event.get("notes"), str) else poi_name,
                "estimated_cost": 0,
                "event_id": event.get("id"),
            })
        merged_days[day_date] = {"date": day_date, "activities": activities}
    expected_day_dates = tuple(
        request.start_date.fromordinal(request.start_date.toordinal() + offset).isoformat()
        for offset in range((request.end_date - request.start_date).days + 1)
    )
    for day_date in expected_day_dates:
        merged_days.setdefault(day_date, {"date": day_date, "activities": []})
    return {"title": generated.get("title"), "days": [merged_days[day_date] for day_date in expected_day_dates]}


def _is_unchanged_empty_target_day(request: GenerationRequest, day_date: date) -> bool:
    if request.target_itinerary_id is None or not isinstance(request.base_snapshot, Mapping):
        return False
    base_days = request.base_snapshot.get("days")
    if not isinstance(base_days, list):
        return False
    matching_day = next((
        day
        for day in base_days
        if isinstance(day, Mapping) and day.get("day_date") == day_date.isoformat()
    ), None)
    return matching_day is None or matching_day.get("events") == []


def _retrieval_document(citation: Citation) -> RetrievalDocument:
    return RetrievalDocument(
        chunk_id=citation.chunk_id,
        document_id=citation.document_id,
        city_code=citation.city_code,
        content=citation.content,
        source_type=citation.source_type,
        source_id=citation.source_id,
        score=1,
    )


def _profile_from_memory_records(records: tuple[MemoryRecord, ...]) -> dict[str, object]:
    profile: dict[str, object] = {}
    for record in records:
        try:
            value = json.loads(record.value)
        except (TypeError, ValueError):
            value = record.value
        profile[record.key] = value
    return profile


def _controlled_review_request(state: WorkflowState) -> GenerationReviewRequest:
    if state.verified_draft is None:
        raise DraftSchemaError("POIs have not been verified")
    documents = tuple(_retrieval_document(citation) for citation in state.citations)
    if not documents:
        documents = tuple(
            RetrievalDocument(
                chunk_id=candidate.source.chunk_id,
                document_id=candidate.source.document_id,
                city_code=candidate.city_code,
                content=candidate.source.content or candidate.poi_name,
                source_type=candidate.source.source_type,
                source_id=candidate.source.source_id,
                score=1,
            )
            for candidate in state.verified_candidates
        )
    if not documents:
        raise DependencyUnavailable("rag_retriever", "No source-backed context is available for review.")
    context = AgentContext(user_id=state.request.user_id, city_code=state.request.city_code)
    evidence_by_poi = {
        candidate.poi_id: candidate.source.chunk_id
        for candidate in state.verified_candidates
    }
    fallback_evidence_chunk_id = documents[0].chunk_id
    planning = PlanningRequest(
        context=context,
        start_date=state.request.start_date,
        end_date=state.request.end_date,
        candidates=tuple(
            PlanningCandidate(
                poi_id=activity.poi.poi_id,
                title=activity.activity.title,
                city_code=activity.poi.city_code,
                estimated_cost=activity.activity.estimated_cost,
                evidence_chunk_id=evidence_by_poi.get(activity.poi.poi_id, fallback_evidence_chunk_id),
            )
            for day in state.verified_draft.days
            for activity in day.activities
        ),
    )
    itinerary = PlannedItinerary(
        city_code=state.request.city_code,
        days=tuple(
            PlannedDay(
                date=day.day_date,
                stops=tuple(
                    PlannedStop(
                        poi_id=activity.poi.poi_id,
                        title=activity.activity.title,
                        estimated_cost=activity.activity.estimated_cost,
                        evidence_chunk_id=evidence_by_poi.get(activity.poi.poi_id, fallback_evidence_chunk_id),
                    )
                    for activity in day.activities
                ),
            )
            for day in state.verified_draft.days
        ),
        total_estimated_cost=sum(
            activity.activity.estimated_cost
            for day in state.verified_draft.days
            for activity in day.activities
        ),
    )
    route = ControlledMapService().build_route(
        MapRouteRequest(
            points=tuple(
                MapPoint(
                    poi_id=activity.poi.poi_id,
                    longitude=activity.poi.longitude,
                    latitude=activity.poi.latitude,
                )
                for day in state.verified_draft.days
                for activity in day.activities
            )
        )
    )
    retrieval = ControlledRetrievalService().retrieve(
        RetrievalRequest(
            context=context,
            query=state.request.prompt,
            limit=min(20, len(documents)),
        ),
        documents,
    )
    return GenerationReviewRequest(
        planning_request=planning,
        itinerary=itinerary,
        retrieval=retrieval,
        route=route,
    )


def _record_production_audit(
    state: WorkflowState,
    node: str,
    started_at: float,
    *,
    agent_version: str,
    tool_summary: Mapping[str, object],
    redacted_summary: str | None = None,
    degradations: tuple[str, ...] = (),
    review_codes: tuple[str, ...] = (),
) -> None:
    previous = state.audit[-1]
    if previous.node != node:
        raise RuntimeError(f"Expected {node} audit entry")
    state.audit[-1] = NodeAudit(
        node=node,
        status=previous.status,
        agent_version=agent_version,
        duration_ms=max(0, round((perf_counter() - started_at) * 1000)),
        redacted_summary=redacted_summary,
        tool_summary=tool_summary,
        degradations=degradations,
        review_codes=review_codes,
    )


def _city_code_matches(requested_city_code: str, poi_adcode: str) -> bool:
    """Allow a prefecture-level AMap code to contain one of its district POIs."""

    if requested_city_code == poi_adcode:
        return True
    if len(requested_city_code) != 6 or len(poi_adcode) != 6 or not requested_city_code.endswith("00"):
        return False
    if requested_city_code[:4] == poi_adcode[:4]:
        return True
    return requested_city_code[:2] in {"11", "12", "31", "50"} and requested_city_code[:2] == poi_adcode[:2]


def _normalize_estimated_cost(value: object) -> int | None:
    if value is None:
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None
