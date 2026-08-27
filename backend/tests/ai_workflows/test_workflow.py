from __future__ import annotations

from datetime import date
from typing import Mapping

import pytest

from app.modules.ai_workflows.contracts import (
    Citation,
    ConstraintCheck,
    SavedPreview,
    VerifiedPlanningCandidate,
    VerifiedItineraryDraft,
    VerifiedPoi,
)
from app.modules.ai_workflows.workflow import (
    ConstraintViolation,
    DependencyUnavailable,
    DraftSchemaError,
    GenerationDependencies,
    GenerationRequest,
    InsufficientVerifiedCandidates,
    LangGraphGenerationWorkflow,
    LangGraphWorkflowFactory,
    LocalWorkflowFactory,
    WORKFLOW_NODES,
    WorkflowState,
    _city_code_matches,
)


class Dependencies:
    def __init__(self, *, citations: tuple[Citation, ...] | None = None, constraint_passes: bool = True) -> None:
        self.citations = citations if citations is not None else (
            Citation("document-1", "chunk-1", "rule", "rule-1", "010", "2026-08-01T00:00:00Z", "source", "poi-1"),
            Citation("document-2", "chunk-2", "rule", "rule-2", "010", "2026-08-01T00:00:00Z", "source", "poi-2"),
        )
        self.constraint_passes = constraint_passes
        self.generation_calls = 0
        self.constraint_checks = 0
        self.saved: tuple[GenerationRequest, VerifiedItineraryDraft, tuple[Citation, ...]] | None = None
        self.saved_audit: tuple[object, ...] | None = None

    async def load_profile_memory(self, user_id: str) -> Mapping[str, object]:
        return {"user_id": user_id, "diet": "vegetarian"}

    async def retrieve(self, request: GenerationRequest) -> tuple[Citation, ...]:
        return self.citations

    async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
        self.generation_calls += 1
        assert request.verified_candidates
        candidates = list(request.verified_candidates)[:2]
        while len(candidates) < 2:
            candidates.append(candidates[0])
        return {"title": "City break", "days": [{"date": "2026-09-01", "activities": [{"poi_id": c.poi_id, "title": c.poi_name, "estimated_cost": 0} for c in candidates]}]}

    async def verify_poi(self, poi_id: str) -> VerifiedPoi:
        names = {"poi-1": "Verified museum", "poi-2": "Verified gallery", "poi-3": "Verified park", "poi-4": "Verified market"}
        return VerifiedPoi(poi_id, names.get(poi_id, "Verified place"), "010", 116.4, 39.9)

    async def discover_scenic_pois(self, city_code: str, limit: int = 10) -> list[VerifiedPoi]:
        return [
            VerifiedPoi("poi-3", "Verified park", "010", 116.41, 39.91),
            VerifiedPoi("poi-4", "Verified market", "010", 116.42, 39.92),
        ][:limit]

    async def check(self, request: GenerationRequest, draft: VerifiedItineraryDraft) -> ConstraintCheck:
        self.constraint_checks += 1
        return ConstraintCheck(self.constraint_passes, () if self.constraint_passes else ("budget exceeded",))

    async def save_preview(self, request: GenerationRequest, draft: VerifiedItineraryDraft, citations: tuple[Citation, ...], audit: tuple[object, ...]) -> SavedPreview:
        self.saved = (request, draft, citations)
        self.saved_audit = audit
        return SavedPreview("preview-1")

    def as_dependencies(self) -> GenerationDependencies:
        return GenerationDependencies(self, self, self, self, self, self, FakeLiveRetriever(), FakeLiveResolver())


class FakeLiveRetriever:
    async def retrieve(self, request: GenerationRequest):
        del request
        return ()


class FakeLiveResolver:
    async def resolve(self, request: GenerationRequest, sources: tuple[object, ...]):
        del request, sources
        return ()


def _two_activities(cost: object = 0) -> list[dict[str, object]]:
    return [
        {"poi_id": "poi-1", "title": "Verified museum", "estimated_cost": cost},
        {"poi_id": "poi-2", "title": "Verified gallery", "estimated_cost": 0},
    ]


class UnavailableProfileMemory(Dependencies):
    async def load_profile_memory(self, user_id: str) -> Mapping[str, object]:
        raise DependencyUnavailable("profile_memory", "Profile memory service is unavailable")


def request() -> GenerationRequest:
    return GenerationRequest("job-1", "user-1", "Plan my trip", "010", date(2026, 9, 1), date(2026, 9, 1), 100)


@pytest.mark.anyio
async def test_local_workflow_runs_documented_preview_path() -> None:
    dependencies = Dependencies()
    state = await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert tuple(entry.node for entry in state.audit) == WORKFLOW_NODES
    assert state.preview == SavedPreview("preview-1")
    assert state.confirmation_required is True
    assert dependencies.saved is not None
    assert dependencies.saved[2] == dependencies.citations


@pytest.mark.anyio
async def test_langgraph_workflow_runs_documented_preview_path() -> None:
    dependencies = Dependencies()
    workflow = LangGraphWorkflowFactory().create(dependencies.as_dependencies())
    state = await workflow.run(request())

    assert isinstance(workflow, LangGraphGenerationWorkflow)
    assert tuple(entry.node for entry in state.audit) == WORKFLOW_NODES
    assert state.preview == SavedPreview("preview-1")
    assert state.confirmation_required is True
    assert dependencies.saved is not None


@pytest.mark.anyio
async def test_workflow_succeeds_with_amap_scenic_when_rag_has_no_sources() -> None:
    """When RAG returns no poi-bound citations, AMap scenic discovery fills the pool."""
    dependencies = Dependencies(citations=())

    state = await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert state.preview == SavedPreview("preview-1")
    assert any(c.source_type == "amap_scenic" for c in state.citations)


@pytest.mark.anyio
async def test_workflow_fails_when_amap_and_live_sources_both_cannot_fill_pool() -> None:
    class NoScenicDependencies(Dependencies):
        async def discover_scenic_pois(self, city_code: str, limit: int = 10) -> list[VerifiedPoi]:
            return []

    class EmptyLiveResolver(FakeLiveResolver):
        async def resolve(self, request: GenerationRequest, sources: tuple[object, ...]):
            return ()

    dependencies = NoScenicDependencies(citations=())
    with pytest.raises(InsufficientVerifiedCandidates, match="Not enough verified places"):
        await LocalWorkflowFactory().create(
            GenerationDependencies(dependencies, dependencies, dependencies, dependencies, dependencies, dependencies, FakeLiveRetriever(), EmptyLiveResolver())
        ).run(request())


@pytest.mark.anyio
async def test_workflow_rejects_a_draft_that_omits_a_selected_must_visit_poi() -> None:
    class OmittingMustVisitDependencies(Dependencies):
        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            return {"title": "Skip must visit", "days": [{"date": "2026-09-01", "activities": [{"poi_id": "poi-1", "title": "Verified museum"}, {"poi_id": "poi-2", "title": "Verified gallery"}]}]}

    dependencies = OmittingMustVisitDependencies()
    must_visit_request = GenerationRequest(
        "job-must-visit",
        "user-1",
        "Plan my trip",
        "010",
        date(2026, 9, 1),
        date(2026, 9, 1),
        100,
        must_visit_poi_ids=("poi-3",),
    )

    with pytest.raises(DraftSchemaError, match="must-visit POI"):
        await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(must_visit_request)


@pytest.mark.anyio
async def test_workflow_prioritizes_approved_candidates_before_live_sources() -> None:
    class ApprovedCandidates:
        async def retrieve(self, _request: GenerationRequest) -> tuple[VerifiedPlanningCandidate, ...]:
            return (
                VerifiedPlanningCandidate("poi-2", "Verified gallery", "010", 116.5, 39.8, Citation("approved-2", "approved-2", "approved_poi", "candidate-2", "010", "2026-08-11T00:00:00Z", "管理员审核景点", "poi-2")),
                VerifiedPlanningCandidate("poi-1", "Verified museum", "010", 116.4, 39.9, Citation("approved-1", "approved-1", "approved_poi", "candidate-1", "010", "2026-08-11T00:00:00Z", "管理员审核景点", "poi-1")),
            )

    class LiveRetriever:
        async def retrieve(self, _request: GenerationRequest):
            raise AssertionError("Approved candidates should avoid live fallback")

    dependencies = Dependencies(citations=())
    workflow = LocalWorkflowFactory().create(GenerationDependencies(
        dependencies, dependencies, dependencies, dependencies, dependencies, dependencies,
        LiveRetriever(), FakeLiveResolver(), ApprovedCandidates(),
    ))
    state = await workflow.run(request())

    assert [candidate.poi_id for candidate in state.verified_candidates] == ["poi-2", "poi-1"]
    assert [citation.source_type for citation in state.citations] == ["approved_poi", "approved_poi"]


@pytest.mark.anyio
async def test_controlled_review_uses_each_verified_candidate_source() -> None:
    class ApprovedCandidates:
        async def retrieve(self, _request: GenerationRequest) -> tuple[VerifiedPlanningCandidate, ...]:
            return (
                VerifiedPlanningCandidate("poi-1", "Verified museum", "010", 116.4, 39.9, Citation("approved-1", "candidate-evidence-1", "approved_poi", "candidate-1", "010", "2026-08-11T00:00:00Z", "管理员审核景点", "poi-1")),
                VerifiedPlanningCandidate("poi-2", "Verified gallery", "010", 116.5, 39.8, Citation("approved-2", "candidate-evidence-2", "approved_poi", "candidate-2", "010", "2026-08-11T00:00:00Z", "管理员审核景点", "poi-2")),
            )

    dependencies = Dependencies(citations=())
    workflow = LocalWorkflowFactory().create(GenerationDependencies(
        dependencies, dependencies, dependencies, dependencies, dependencies, dependencies,
        FakeLiveRetriever(), FakeLiveResolver(), ApprovedCandidates(),
    ))
    state = await workflow.run(request())

    assert state.preview == SavedPreview("preview-1")


@pytest.mark.anyio
async def test_live_candidates_keep_distinct_evidence_when_they_share_one_source_url() -> None:
    class NoScenicDependencies(Dependencies):
        async def discover_scenic_pois(self, city_code: str, limit: int = 10) -> list[VerifiedPoi]:
            return []

    class LiveRetriever:
        async def retrieve(self, _request: GenerationRequest):
            return (object(),)

    class LiveResolver:
        async def resolve(self, _request: GenerationRequest, _sources: tuple[object, ...]):
            return (
                VerifiedPlanningCandidate("poi-1", "Verified museum", "010", 116.4, 39.9, Citation("doc-a", "evidence-a", "live_web", "https://example.cn/guide", "010", "2026-08-11T00:00:00Z", "Museum", "poi-1")),
                VerifiedPlanningCandidate("poi-2", "Verified gallery", "010", 116.5, 39.8, Citation("doc-b", "evidence-b", "live_web", "https://example.cn/guide", "010", "2026-08-11T00:00:00Z", "Gallery", "poi-2")),
            )

    dependencies = NoScenicDependencies(citations=())
    workflow = LocalWorkflowFactory().create(GenerationDependencies(
        dependencies, dependencies, dependencies, dependencies, dependencies, dependencies,
        LiveRetriever(), LiveResolver(), None,
    ))
    state = await workflow.run(request())

    assert {citation.chunk_id for citation in state.citations} == {"evidence-a", "evidence-b"}


@pytest.mark.anyio
async def test_controlled_review_keeps_evidence_for_all_used_live_candidates() -> None:
    class LiveRetriever:
        async def retrieve(self, _request: GenerationRequest):
            return (object(),)

    class LiveResolver:
        async def resolve(self, _request: GenerationRequest, _sources: tuple[object, ...]):
            return tuple(
                VerifiedPlanningCandidate(
                    f"poi-{index}",
                    f"Verified place {index}",
                    "010",
                    116.4 + index / 100,
                    39.8 + index / 100,
                    Citation(f"doc-{index}", f"evidence-{index}", "live_web", f"https://example.cn/{index}", "010", "2026-08-11T00:00:00Z", f"Place {index}", f"poi-{index}"),
                )
                for index in range(1, 10)
            )

    class NineStopDependencies(Dependencies):
        async def discover_scenic_pois(self, city_code: str, limit: int = 10) -> list[VerifiedPoi]:
            return []

        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            return {
                "title": "Three days",
                "days": [
                    {"date": "2026-09-01", "activities": [{"poi_id": "poi-1", "title": "Verified place 1"}, {"poi_id": "poi-2", "title": "Verified place 2"}, {"poi_id": "poi-3", "title": "Verified place 3"}]},
                    {"date": "2026-09-02", "activities": [{"poi_id": "poi-4", "title": "Verified place 4"}, {"poi_id": "poi-5", "title": "Verified place 5"}, {"poi_id": "poi-6", "title": "Verified place 6"}]},
                    {"date": "2026-09-03", "activities": [{"poi_id": "poi-7", "title": "Verified place 7"}, {"poi_id": "poi-8", "title": "Verified place 8"}, {"poi_id": "poi-9", "title": "Verified place 9"}]},
                ],
            }

    dependencies = NineStopDependencies(citations=())
    workflow = LangGraphWorkflowFactory().create(GenerationDependencies(
        dependencies, dependencies, dependencies, dependencies, dependencies, dependencies,
        LiveRetriever(), LiveResolver(), None,
    ))
    state = await workflow.run(GenerationRequest("job-nine", "user-1", "Plan my trip", "010", date(2026, 9, 1), date(2026, 9, 3), 100))

    assert state.preview == SavedPreview("preview-1")


@pytest.mark.anyio
async def test_workflow_does_not_call_live_search_when_reviewed_candidates_cover_all_days() -> None:
    class CountingLiveRetriever(FakeLiveRetriever):
        def __init__(self) -> None:
            self.calls = 0

        async def retrieve(self, request: GenerationRequest):
            self.calls += 1
            return await super().retrieve(request)

    class TwoDayDependencies(Dependencies):
        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            return {
                "title": "Two days",
                "days": [
                    {"date": "2026-09-01", "activities": _two_activities()},
                    {"date": "2026-09-02", "activities": [
                        {"poi_id": "poi-3", "title": "Verified park"},
                        {"poi_id": "poi-4", "title": "Verified market"},
                    ]},
                ],
            }

    dependencies = TwoDayDependencies(citations=tuple(
        Citation(f"document-{index}", f"chunk-{index}", "rule", f"rule-{index}", "010", "2026-08-01T00:00:00Z", "source", f"poi-{index}")
        for index in range(1, 5)
    ))
    live_retriever = CountingLiveRetriever()
    workflow = LocalWorkflowFactory().create(
        GenerationDependencies(dependencies, dependencies, dependencies, dependencies, dependencies, dependencies, live_retriever, FakeLiveResolver())
    )

    phases: list[str] = []

    async def record_progress(phase: str) -> None:
        phases.append(phase)

    await workflow.run(GenerationRequest("job-2", "user-1", "Plan my trip", "010", date(2026, 9, 1), date(2026, 9, 2), 100, progress_callback=record_progress))

    assert live_retriever.calls == 0
    assert phases == ["retrieving_reviewed_sources", "verifying_pois", "planning", "validating"]


@pytest.mark.anyio
async def test_workflow_uses_live_sources_once_when_reviewed_candidates_are_insufficient() -> None:
    class NoScenicDependencies(Dependencies):
        async def discover_scenic_pois(self, city_code: str, limit: int = 10) -> list[VerifiedPoi]:
            return []

    class LiveRetriever:
        def __init__(self) -> None:
            self.calls = 0

        async def retrieve(self, request: GenerationRequest):
            from app.modules.ai_workflows.live_sources import LiveSourceCandidate

            self.calls += 1
            return (LiveSourceCandidate("Gallery", "https://example.cn/gallery", "example.cn", "Gallery details"),)

    class LiveResolver:
        async def resolve(self, request: GenerationRequest, sources: tuple[object, ...]):
            assert len(sources) == 1
            return (VerifiedPlanningCandidate("poi-2", "Verified gallery", "010", 116.5, 39.8, Citation("live-doc", "live-chunk", "live_web", "https://example.cn/gallery", "010", "2026-08-01T00:00:00Z", "Gallery details")),)

    dependencies = NoScenicDependencies(citations=(Citation("document-1", "chunk-1", "rule", "rule-1", "010", "2026-08-01T00:00:00Z", "source", "poi-1"),))
    live_retriever = LiveRetriever()
    workflow = LocalWorkflowFactory().create(
        GenerationDependencies(dependencies, dependencies, dependencies, dependencies, dependencies, dependencies, live_retriever, LiveResolver())
    )

    phases: list[str] = []

    async def record_progress(phase: str) -> None:
        phases.append(phase)

    state = await workflow.run(GenerationRequest("job-1", "user-1", "Plan my trip", "010", date(2026, 9, 1), date(2026, 9, 1), 100, progress_callback=record_progress))

    assert live_retriever.calls == 1
    assert state.live_source_used is True
    assert all(len(day.activities) >= 2 for day in state.verified_draft.days)
    assert any(citation.source_type == "live_web" for citation in state.citations)
    assert phases == ["retrieving_reviewed_sources", "searching_live_sources", "verifying_pois", "planning", "validating"]


@pytest.mark.anyio
async def test_workflow_uses_amap_scenic_discovery_when_rag_citations_are_insufficient() -> None:
    """When RAG has too few poi-bound citations, AMap scenic discovery fills the pool
    without depending on the web-search MCP."""
    dependencies = Dependencies(citations=(Citation("document-1", "chunk-1", "rule", "rule-1", "010", "2026-08-01T00:00:00Z", "source", "poi-1"),))

    state = await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(
        GenerationRequest("job-1", "user-1", "Plan my trip", "010", date(2026, 9, 1), date(2026, 9, 1), 100)
    )

    assert state.live_source_used is False
    assert any(citation.source_type == "amap_scenic" for citation in state.citations)
    assert {c.poi_id for c in state.verified_candidates} >= {"poi-1", "poi-3", "poi-4"}


@pytest.mark.anyio
async def test_workflow_survives_broken_web_search_after_amap_scenic_fills_pool() -> None:
    """AMap scenic discovery fills enough POIs; a dead web-search MCP is silently ignored."""
    class BrokenWebSearchRetriever:
        async def retrieve(self, request: GenerationRequest):
            raise RuntimeError("MCP 404")

    class CountingResolver(FakeLiveResolver):
        def __init__(self) -> None:
            self.called = False
        async def resolve(self, request: GenerationRequest, sources: tuple[object, ...]):
            self.called = True
            return await super().resolve(request, sources)

    dependencies = Dependencies(citations=(Citation("document-1", "chunk-1", "rule", "rule-1", "010", "2026-08-01T00:00:00Z", "source", "poi-1"),))
    resolver = CountingResolver()
    workflow = LocalWorkflowFactory().create(
        GenerationDependencies(dependencies, dependencies, dependencies, dependencies, dependencies, dependencies, BrokenWebSearchRetriever(), resolver)
    )

    state = await workflow.run(GenerationRequest("job-1", "user-1", "Plan my trip", "010", date(2026, 9, 1), date(2026, 9, 1), 100))

    assert resolver.called is False  # pool already full, live sources never reached
    assert state.live_source_used is False
    assert all(len(day.activities) >= 2 for day in state.verified_draft.days)


@pytest.mark.anyio
async def test_workflow_raises_exact_no_result_message_when_verified_pool_is_insufficient() -> None:
    class NoScenicDependencies(Dependencies):
        async def discover_scenic_pois(self, city_code: str, limit: int = 10) -> list[VerifiedPoi]:
            return []

    class EmptyLiveResolver(FakeLiveResolver):
        async def resolve(self, request: GenerationRequest, sources: tuple[object, ...]):
            return ()

    dependencies = NoScenicDependencies(citations=(Citation("document-1", "chunk-1", "rule", "rule-1", "010", "2026-08-01T00:00:00Z", "source", "poi-1"),))

    with pytest.raises(InsufficientVerifiedCandidates, match="^Not enough verified places were found for this trip\\.$"):
        await LocalWorkflowFactory().create(
            GenerationDependencies(dependencies, dependencies, dependencies, dependencies, dependencies, dependencies, FakeLiveRetriever(), EmptyLiveResolver())
        ).run(request())


@pytest.mark.anyio
async def test_workflow_propagates_typed_dependency_unavailability() -> None:
    dependencies = UnavailableProfileMemory()

    with pytest.raises(DependencyUnavailable) as error:
        await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert error.value.dependency == "profile_memory"


@pytest.mark.anyio
async def test_langgraph_workflow_propagates_typed_dependency_unavailability() -> None:
    dependencies = UnavailableProfileMemory()

    with pytest.raises(DependencyUnavailable) as error:
        await LangGraphWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert error.value.dependency == "profile_memory"


@pytest.mark.anyio
async def test_workflow_does_not_save_a_constraint_violating_preview() -> None:
    dependencies = Dependencies(constraint_passes=False)

    with pytest.raises(ConstraintViolation, match="budget exceeded"):
        await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert dependencies.saved is None


@pytest.mark.anyio
async def test_langgraph_workflow_does_not_save_a_constraint_violating_preview() -> None:
    dependencies = Dependencies(constraint_passes=False)

    with pytest.raises(ConstraintViolation, match="budget exceeded"):
        await LangGraphWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert dependencies.saved is None


@pytest.mark.anyio
async def test_langgraph_workflow_ignores_foreign_profile_and_foreign_city_evidence() -> None:
    class ScopedDependencies(Dependencies):
        def __init__(self) -> None:
            super().__init__(
                citations=(
                    Citation("document-foreign", "chunk-foreign", "rule", "rule-foreign", "020", "2026-08-01T00:00:00Z", "foreign", "poi-foreign"),
                    Citation("document-local", "chunk-local", "rule", "rule-local", "010", "2026-08-01T00:00:00Z", "local", "poi-1"),
                    Citation("document-local-2", "chunk-local-2", "rule", "rule-local-2", "010", "2026-08-01T00:00:00Z", "local", "poi-2"),
                )
            )
            self.generated_profile: Mapping[str, object] | None = None
            self.generated_citations: tuple[Citation, ...] | None = None

        async def load_profile_memory(self, user_id: str) -> Mapping[str, object]:
            return {"user_id": "another-user", "diet": "foreign-preference"}

        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            self.generated_profile = profile_memory
            self.generated_citations = citations
            return await super().generate(request, profile_memory, citations)

    dependencies = ScopedDependencies()
    state = await LangGraphWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert state.preview == SavedPreview("preview-1")
    assert dependencies.generated_profile == {}
    assert dependencies.generated_citations == dependencies.citations[1:]
    retrieval_audit = next(entry for entry in state.audit if entry.node == "retrieval_agent")
    assert retrieval_audit.degradations == ("foreign_city_citations_filtered",)


@pytest.mark.anyio
async def test_langgraph_controlled_review_prevents_duplicate_poi_preview() -> None:
    class DuplicatePoiDependencies(Dependencies):
        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            return {
                "title": "Duplicate plan",
                "days": [
                    {"date": "2026-09-01", "activities": _two_activities()},
                    {"date": "2026-09-02", "activities": [
                        {"poi_id": "poi-1", "title": "Verified museum"},
                        {"poi_id": "poi-2", "title": "Verified gallery"},
                    ]},
                ],
            }

    dependencies = DuplicatePoiDependencies(citations=(
        Citation("document-1", "chunk-1", "rule", "rule-1", "010", "2026-08-01T00:00:00Z", "source", "poi-1"),
        Citation("document-2", "chunk-2", "rule", "rule-2", "010", "2026-08-01T00:00:00Z", "source", "poi-2"),
        Citation("document-3", "chunk-3", "rule", "rule-3", "010", "2026-08-01T00:00:00Z", "source", "poi-3"),
        Citation("document-4", "chunk-4", "rule", "rule-4", "010", "2026-08-01T00:00:00Z", "source", "poi-4"),
    ))
    duplicate_request = GenerationRequest("job-duplicate", "user-1", "Plan my trip", "010", date(2026, 9, 1), date(2026, 9, 2), 100)

    with pytest.raises(DraftSchemaError, match="must not repeat a POI"):
        await LangGraphWorkflowFactory().create(dependencies.as_dependencies()).run(duplicate_request)

    assert dependencies.saved is None


@pytest.mark.anyio
async def test_workflow_retries_planning_at_most_twice_for_failed_review() -> None:
    dependencies = Dependencies(constraint_passes=False)

    with pytest.raises(ConstraintViolation, match="budget exceeded"):
        await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert dependencies.generation_calls == 3
    assert dependencies.constraint_checks == 3


@pytest.mark.anyio
async def test_workflow_persists_revision_review_audit_with_preview() -> None:
    class RevisableDependencies(Dependencies):
        async def check(self, request: GenerationRequest, draft: VerifiedItineraryDraft) -> ConstraintCheck:
            self.constraint_checks += 1
            if self.constraint_checks == 1:
                return ConstraintCheck(False, ("budget exceeded",))
            return ConstraintCheck(True)

    dependencies = RevisableDependencies()
    state = await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())

    assert state.revision_count == 1
    assert dependencies.generation_calls == 2
    assert dependencies.saved_audit is not None
    assert [(entry.node, entry.status) for entry in dependencies.saved_audit] == [
        ("validate_request", "completed"),
        ("memory_retrieval_agent", "completed"),
        ("retrieval_agent", "completed"),
        ("planning_agent", "completed"),
        ("validate_schema", "completed"),
        ("map_agent", "completed"),
        ("generation_review_agent", "revision_1_requested"),
        ("planning_agent", "completed"),
        ("validate_schema", "completed"),
        ("map_agent", "completed"),
        ("generation_review_agent", "passed_after_1_revisions"),
    ]


@pytest.mark.anyio
async def test_workflow_records_terminal_constraint_review_after_two_revisions() -> None:
    dependencies = Dependencies(constraint_passes=False)
    workflow = LocalWorkflowFactory().create(dependencies.as_dependencies())
    state = WorkflowState(request=request(), verified_draft=VerifiedItineraryDraft("City break", ()))

    assert (await workflow._check_date_budget_route_constraints(state)).retry_planning is True
    assert (await workflow._check_date_budget_route_constraints(state)).retry_planning is True
    with pytest.raises(ConstraintViolation, match="budget exceeded"):
        await workflow._check_date_budget_route_constraints(state)

    assert state.revision_count == 2
    assert [(entry.node, entry.status) for entry in state.audit] == [
        ("generation_review_agent", "revision_1_requested"),
        ("generation_review_agent", "revision_2_requested"),
        ("generation_review_agent", "terminal_after_2_revisions"),
    ]


@pytest.mark.anyio
async def test_workflow_rejects_empty_or_incomplete_draft_days() -> None:
    class EmptyDraftDependencies(Dependencies):
        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            self.generation_calls += 1
            return {"title": "Empty plan", "days": [{"date": "2026-09-01", "activities": []}]}

    dependencies = EmptyDraftDependencies()
    with pytest.raises(InsufficientVerifiedCandidates, match="Not enough verified places"):
        await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())
    assert dependencies.saved is None
    assert dependencies.generation_calls == 1
    assert dependencies.constraint_checks == 0


@pytest.mark.anyio
async def test_targeted_workflow_preserves_an_unchanged_empty_base_day() -> None:
    class PartialModificationDependencies(Dependencies):
        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            return {
                "title": "Updated city break",
                "days": [{"date": "2026-09-01", "activities": [{"poi_id": "poi-1", "title": "Museum"}]}],
            }

    dependencies = PartialModificationDependencies()
    targeted_request = GenerationRequest(
        "job-targeted", "user-1", "Move the museum", "010", date(2026, 9, 1), date(2026, 9, 2), 100,
        target_itinerary_id="itinerary-1",
        base_version=3,
        base_snapshot={
            "days": [
                {"day_date": "2026-09-01", "events": [{"poi_id": "poi-1", "poi_snapshot": {"name": "Museum", "location": {"longitude": 116.4, "latitude": 39.9}}}]},
            ],
        },
    )

    state = await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(targeted_request)

    assert state.preview == SavedPreview("preview-1")
    assert state.draft is not None
    assert [len(day.activities) for day in state.draft.days] == [1, 0]

    langgraph_state = await LangGraphWorkflowFactory().create(dependencies.as_dependencies()).run(targeted_request)

    assert langgraph_state.preview == SavedPreview("preview-1")
    assert langgraph_state.draft is not None
    assert [len(day.activities) for day in langgraph_state.draft.days] == [1, 0]


@pytest.mark.anyio
async def test_workflow_normalizes_integral_json_number_costs() -> None:
    class IntegralFloatDependencies(Dependencies):
        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            return {"title": "City break", "days": [{"date": "2026-09-01", "activities": _two_activities(0.0)}]}

    dependencies = IntegralFloatDependencies()
    state = await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())
    assert state.draft is not None
    assert state.draft.days[0].activities[0].estimated_cost == 0


@pytest.mark.anyio
async def test_workflow_normalizes_integer_cost_strings_but_rejects_fractional_costs() -> None:
    class IntegerStringDependencies(Dependencies):
        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            return {
                "title": "City break",
                "days": [{"date": "2026-09-01", "activities": _two_activities("0")}],
            }

    dependencies = IntegerStringDependencies()
    state = await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())
    assert state.draft is not None
    assert state.draft.days[0].activities[0].estimated_cost == 0


@pytest.mark.anyio
async def test_workflow_treats_unspecified_cost_as_zero_without_accepting_text() -> None:
    class NoCostDependencies(Dependencies):
        async def generate(self, request: GenerationRequest, profile_memory: Mapping[str, object], citations: tuple[Citation, ...]) -> Mapping[str, object]:
            return {"title": "City break", "days": [{"date": "2026-09-01", "activities": _two_activities(None)}]}

    dependencies = NoCostDependencies()
    state = await LocalWorkflowFactory().create(dependencies.as_dependencies()).run(request())
    assert state.draft is not None
    assert state.draft.days[0].activities[0].estimated_cost == 0


def test_city_code_match_accepts_district_poi_for_prefecture_and_municipality_requests() -> None:
    assert _city_code_matches("330100", "330106")
    assert _city_code_matches("330100", "330100")
    assert _city_code_matches("110000", "110105")
    assert _city_code_matches("120000", "120101")
    assert _city_code_matches("310000", "310101")
    assert _city_code_matches("500000", "500101")
    assert not _city_code_matches("330100", "310101")
    assert not _city_code_matches("330106", "330100")
