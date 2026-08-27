from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AgentContext(AgentModel):
    user_id: str = Field(min_length=1, max_length=128)
    city_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class RetrievalRequest(AgentModel):
    context: AgentContext
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=8, ge=1, le=20)


class RetrievalDocument(AgentModel):
    chunk_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    city_code: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=10_000)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=128)
    score: float = Field(ge=0, le=1)


class RetrievalResult(AgentModel):
    query: str
    documents: tuple[RetrievalDocument, ...]


class MemoryRecord(AgentModel):
    memory_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    key: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0, le=1)


class MemoryRetrievalRequest(AgentModel):
    context: AgentContext
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=10, ge=1, le=20)


class MemoryRetrievalResult(AgentModel):
    query: str
    records: tuple[MemoryRecord, ...]


class PlanningCandidate(AgentModel):
    poi_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    city_code: str = Field(min_length=1, max_length=32)
    estimated_cost: int = Field(default=0, ge=0)
    evidence_chunk_id: str = Field(min_length=1, max_length=128)
    available_on: tuple[date, ...] = ()


class PlanningRequest(AgentModel):
    context: AgentContext
    start_date: date
    end_date: date
    candidates: tuple[PlanningCandidate, ...] = Field(min_length=1, max_length=42)

    @model_validator(mode="after")
    def validate_dates(self) -> "PlanningRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if (self.end_date - self.start_date).days >= 7:
            raise ValueError("planning requests may span at most seven days")
        return self


class PlannedStop(AgentModel):
    poi_id: str
    title: str
    estimated_cost: int = Field(ge=0)
    evidence_chunk_id: str


class PlannedDay(AgentModel):
    date: date
    stops: tuple[PlannedStop, ...] = ()


class PlannedItinerary(AgentModel):
    city_code: str
    days: tuple[PlannedDay, ...] = Field(min_length=1)
    total_estimated_cost: int = Field(ge=0)


class MapPoint(AgentModel):
    poi_id: str = Field(min_length=1, max_length=128)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class MapRouteRequest(AgentModel):
    points: tuple[MapPoint, ...] = Field(min_length=1, max_length=50)


class MapLeg(AgentModel):
    from_poi_id: str
    to_poi_id: str
    distance_meters: int = Field(ge=0)


class MapRoute(AgentModel):
    ordered_poi_ids: tuple[str, ...] = Field(min_length=1)
    legs: tuple[MapLeg, ...]
    total_distance_meters: int = Field(ge=0)


class ReviewIssue(AgentModel):
    code: Literal[
        "MISSING_RETRIEVAL_EVIDENCE",
        "DUPLICATE_POI",
        "MAP_ROUTE_MISMATCH",
        "ITINERARY_CITY_MISMATCH",
        "ITINERARY_DATE_MISMATCH",
    ]
    message: str
    day: date | None = None
    poi_id: str | None = None


class GenerationReviewRequest(AgentModel):
    planning_request: PlanningRequest
    itinerary: PlannedItinerary
    retrieval: RetrievalResult
    route: MapRoute


class GenerationReviewResult(AgentModel):
    approved: bool
    issues: tuple[ReviewIssue, ...]
