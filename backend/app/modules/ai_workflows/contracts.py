from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable, Mapping, Protocol


ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class GenerationRequest:
    generation_job_id: str
    user_id: str
    prompt: str
    city_code: str
    start_date: date
    end_date: date
    budget_amount: int | None = None
    currency: str = "CNY"
    target_itinerary_id: str | None = None
    base_version: int | None = None
    base_snapshot: Mapping[str, Any] | None = None
    verified_candidates: tuple["VerifiedPlanningCandidate", ...] = ()
    progress_callback: ProgressCallback | None = None
    workflow_run_id: str | None = None
    preference_tags: tuple[str, ...] = ()
    must_visit_poi_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Citation:
    document_id: str
    chunk_id: str
    source_type: str
    source_id: str
    city_code: str
    source_updated_at: str
    content: str
    poi_id: str | None = None


@dataclass(frozen=True)
class DraftActivity:
    poi_id: str
    title: str
    estimated_cost: int = 0
    event_id: str | None = None


@dataclass(frozen=True)
class DraftDay:
    day_date: date
    activities: tuple[DraftActivity, ...]


@dataclass(frozen=True)
class ItineraryDraft:
    title: str
    days: tuple[DraftDay, ...]


@dataclass(frozen=True)
class VerifiedPoi:
    poi_id: str
    name: str
    city_code: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class VerifiedActivity:
    activity: DraftActivity
    poi: VerifiedPoi


@dataclass(frozen=True)
class VerifiedDay:
    day_date: date
    activities: tuple[VerifiedActivity, ...]


@dataclass(frozen=True)
class VerifiedItineraryDraft:
    title: str
    days: tuple[VerifiedDay, ...]


@dataclass(frozen=True)
class ConstraintCheck:
    passed: bool
    violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class SavedPreview:
    preview_id: str


class ProfileMemoryLoader(Protocol):
    async def load_profile_memory(self, user_id: str) -> Mapping[str, object]: ...


class RAGRetriever(Protocol):
    async def retrieve(self, request: GenerationRequest) -> tuple[Citation, ...]: ...


class ApprovedPlanningCandidateRetriever(Protocol):
    async def retrieve(self, request: GenerationRequest) -> tuple["VerifiedPlanningCandidate", ...]: ...


class StructuredDraftGenerator(Protocol):
    async def generate(
        self,
        request: GenerationRequest,
        profile_memory: Mapping[str, object],
        citations: tuple[Citation, ...],
    ) -> Mapping[str, object]: ...


class AMapPoiVerifier(Protocol):
    async def verify_poi(self, poi_id: str) -> VerifiedPoi: ...
    async def discover_scenic_pois(self, city_code: str, limit: int = ...) -> list[VerifiedPoi]: ...


@dataclass(frozen=True)
class VerifiedPlanningCandidate:
    poi_id: str
    poi_name: str
    city_code: str
    longitude: float
    latitude: float
    source: Citation


class LiveSourceRetriever(Protocol):
    async def retrieve(self, request: GenerationRequest) -> tuple["LiveSourceCandidate", ...]: ...


class LiveSourceResolver(Protocol):
    async def resolve(
        self, request: GenerationRequest, sources: tuple["LiveSourceCandidate", ...]
    ) -> tuple[VerifiedPlanningCandidate, ...]: ...


class ItineraryConstraintChecker(Protocol):
    async def check(
        self, request: GenerationRequest, draft: VerifiedItineraryDraft
    ) -> ConstraintCheck: ...


class PreviewStore(Protocol):
    async def save_preview(
        self,
        request: GenerationRequest,
        draft: VerifiedItineraryDraft,
        citations: tuple[Citation, ...],
        audit: tuple["NodeAudit", ...],
    ) -> SavedPreview: ...


@dataclass(frozen=True)
class NodeAudit:
    node: str
    status: str
    agent_version: str | None = None
    duration_ms: int | None = None
    redacted_summary: str | None = None
    tool_summary: Mapping[str, object] | None = None
    degradations: tuple[str, ...] = ()
    review_codes: tuple[str, ...] = ()
