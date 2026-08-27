from __future__ import annotations

from datetime import date as CalendarDate, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


CityCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")]
SourceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class StrictModel(BaseModel):
    """Reject fields outside the published AI planning contracts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AiPlanningRequest(StrictModel):
    """Input available to a planning model; it does not identify a persisted itinerary."""

    city_code: CityCode
    request: str = Field(min_length=1, max_length=2_000)
    start_date: CalendarDate | None = None
    end_date: CalendarDate | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> AiPlanningRequest:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be provided together.")
        if self.start_date and self.end_date:
            duration = (self.end_date - self.start_date).days + 1
            if not 1 <= duration <= 7:
                raise ValueError("A planning request must span one to seven days.")
        return self


class RetrievedSource(StrictModel):
    """Trusted retrieval metadata supplied by the RAG layer, never by the model."""

    source_id: SourceId
    source_type: Literal["community", "amap", "travel_rule", "itinerary_template"]
    city_code: CityCode
    status: Literal["approved", "verified"]
    source_updated_at: datetime


class Citation(StrictModel):
    """A model-provided reference to a source record supplied in `RetrievedSource`."""

    citation_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    source_id: SourceId
    claim: str = Field(min_length=1, max_length=1_000)


class DraftEvent(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2_000)
    citation_ids: list[str] = Field(min_length=1, max_length=8)


class DraftDay(StrictModel):
    date: CalendarDate | None = None
    events: list[DraftEvent] = Field(min_length=1, max_length=12)


class PlanningDraft(StrictModel):
    """The only allowed AI success payload: a confirmation-required preview."""

    kind: Literal["itinerary_preview"]
    preview_only: Literal[True]
    confirmation_required: Literal[True]
    city_code: CityCode
    title: str = Field(min_length=1, max_length=160)
    confidence: float = Field(ge=0, le=1)
    citations: list[Citation] = Field(min_length=1, max_length=32)
    days: list[DraftDay] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def validate_citation_references_and_dates(self) -> PlanningDraft:
        citation_ids = [citation.citation_id for citation in self.citations]
        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("citation_id values must be unique.")

        known_ids = set(citation_ids)
        for day in self.days:
            for event in day.events:
                if len(event.citation_ids) != len(set(event.citation_ids)):
                    raise ValueError("event citation_ids must be unique.")
                if unknown := set(event.citation_ids) - known_ids:
                    raise ValueError(f"event references unknown citations: {sorted(unknown)}")

        dated_days = [day.date for day in self.days if day.date is not None]
        if dated_days and len(dated_days) != len(self.days):
            raise ValueError("all draft days must have dates when any draft day is dated.")
        if len(dated_days) != len(set(dated_days)):
            raise ValueError("draft day dates must be unique.")
        return self


AMapSource = RetrievedSource
