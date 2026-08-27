from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.itineraries.schemas import SelectedDestination


PreferenceTag = Literal[
    "经典必玩",
    "吃吃喝喝",
    "小众探索",
    "拍照出片",
    "逛街购物",
    "citywalk",
    "自然风光",
    "文艺展览",
    "历史古建",
]

GenerationJobStatus = Literal[
    "queued",
    "understanding",
    "resolving_destination",
    "retrieving",
    "retrieving_reviewed_sources",
    "searching_live_sources",
    "verifying_pois",
    "planning",
    "validating",
    "awaiting_confirmation",
    "succeeded",
    "failed",
    "cancelled",
]


class GenerationJobCreate(BaseModel):
    destination: SelectedDestination | None = None
    prompt: str = Field(default="", max_length=2000)
    start_date: date
    end_date: date
    preference_tags: list[PreferenceTag] | None = Field(default=None, max_length=3)
    budget_amount: int | None = Field(default=None, ge=0)
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    traveler_count: int = Field(default=1, ge=1, le=20)
    pace: Literal["slow", "balanced", "fast"] | None = None
    traveler_type: Literal["solo", "couple", "friends", "family"] | None = None
    must_visit_poi_ids: list[str] = Field(default_factory=list, max_length=20)
    avoid_poi_ids: list[str] = Field(default_factory=list, max_length=20)
    target_itinerary_id: str | None = None
    base_version: int | None = Field(default=None, ge=1)

    @property
    def city_code(self) -> str:
        """Retain the workflow's canonical city code without exposing a free-text field."""
        if self.destination is None:
            raise ValueError("destination is required when no target itinerary is supplied.")
        return self.destination.city_code

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_dates(self) -> "GenerationJobCreate":
        if not 1 <= (self.end_date - self.start_date).days + 1 <= 7:
            raise ValueError("A generation request must span one to seven days.")
        if self.target_itinerary_id is None and self.start_date < date.today():
            # Modification requests echo the target itinerary's own dates, which may already be in progress.
            raise ValueError("start_date must not be in the past.")
        if self.preference_tags is not None and len(set(self.preference_tags)) != len(self.preference_tags):
            raise ValueError("preference_tags must not contain duplicates.")
        if (self.target_itinerary_id is None) != (self.base_version is None):
            raise ValueError("target_itinerary_id and base_version must be supplied together.")
        if self.target_itinerary_id is None and self.destination is None:
            raise ValueError("destination is required for a new itinerary.")
        return self


class GenerationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: GenerationJobStatus
    progress: int
    outcome: Literal["preview", "no_result", "clarification", "unavailable"] | None
    error_code: str | None
    message: str | None
    preview_id: str | None
    attempt_count: int
    last_attempt_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    trace_id: str | None
    finished_at: datetime | None
    target_itinerary_id: str | None
    created_at: datetime
    updated_at: datetime


class GenerationJobEvent(BaseModel):
    job_id: str
    status: str
    progress: int
    trace_id: str
    outcome: str | None = None
    error_code: str | None = None
    preview_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class GenerationPreviewResponse(BaseModel):
    id: str
    generation_job_id: str
    draft: dict[str, Any]
    citations: list[dict[str, Any]]
    prompt_version: str | None
    model_version: str | None
    created_at: datetime
    target_itinerary_id: str | None = None
    base_version: int | None = None
