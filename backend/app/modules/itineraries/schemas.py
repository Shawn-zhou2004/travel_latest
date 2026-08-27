from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import validate_uuid_v4


class CreateItineraryRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    start_date: date
    end_date: date

    def model_post_init(self, __context: Any) -> None:
        if not 1 <= (self.end_date - self.start_date).days + 1 <= 7:
            raise ValueError("An itinerary must span one to seven days.")


class SelectedDestination(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    display_address: str = Field(min_length=1, max_length=300)
    city_code: str = Field(pattern=r"^\d{6}$")


class ManualPlanCreateRequest(BaseModel):
    destination: SelectedDestination
    start_date: date
    end_date: date
    title: str | None = Field(default=None, max_length=160)

    def model_post_init(self, __context: Any) -> None:
        duration = (self.end_date - self.start_date).days + 1
        if not 1 <= duration <= 7:
            raise ValueError("An itinerary must span one to seven days.")
        if self.start_date < date.today():
            raise ValueError("start_date must not be in the past.")


class OperationRequest(BaseModel):
    operation_type: Literal["add_day", "remove_day", "add_event", "remove_event", "update_event", "reorder_event", "recalculate_route", "apply_ai_preview"]
    payload: dict[str, Any] = Field(default_factory=dict)


class ItineraryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    owner_id: str
    title: str
    start_date: date
    end_date: date
    version: int
    status: str
    created_at: datetime
    updated_at: datetime
    source_post_id: str | None = None
    access_role: Literal["owner", "editor", "viewer"] | None = None


class ItineraryDetailResponse(ItineraryResponse):
    snapshot: dict[str, Any]
    access_role: Literal["owner", "editor", "viewer"] = "owner"


class CompanionWorkspaceSummaryResponse(BaseModel):
    id: str
    status: Literal["open", "full", "closed", "cancelled", "completed"]
    review_status: Literal["pending_review", "approved", "rejected"] | None = None
    party_size: int
    accepted_count: int
    role: Literal["owner", "member", "collaborator"]
    conversation_id: str | None = None


class ItineraryVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    version_no: int
    source: str
    created_at: datetime


class ItineraryVersionDetailResponse(ItineraryVersionResponse):
    snapshot: dict[str, Any]


class RouteCalculationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    day_id: str
    status: Literal["queued", "calculating", "completed", "failed"]
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class OperationResponse(BaseModel):
    code: Literal["APPLIED", "VERSION_CONFLICT", "FORBIDDEN", "NOT_FOUND", "MAP_UNAVAILABLE", "PREVIEW_INVALID", "PREVIEW_TARGET_NOT_EMPTY"]
    current_version: int | None = None
    snapshot: dict[str, Any] | None = None
    idempotent: bool = False
    route_job: RouteCalculationJobResponse | None = None


class RestoreVersionRequest(BaseModel):
    version: int = Field(ge=1)


class CreateShareTokenRequest(BaseModel):
    expires_at: datetime | None = None


class ShareTokenResponse(BaseModel):
    id: str
    share_url: str
    token: str
    expires_at: datetime | None


class InviteCollaboratorRequest(BaseModel):
    user_id: str
    role: Literal["viewer", "editor"]

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        return validate_uuid_v4(value, "user_id")


class UpdateCollaboratorRequest(BaseModel):
    role: Literal["viewer", "editor"] | None = None
    invite_status: Literal["pending", "revoked"] | None = None


class CollaboratorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    role: Literal["viewer", "editor"]
    invite_status: Literal["pending", "accepted", "revoked"]


class PublicItineraryResponse(BaseModel):
    id: str
    title: str
    start_date: date
    end_date: date
    version: int
    status: str
    snapshot: dict[str, Any]
    access_role: Literal["viewer"] = "viewer"


class FieldNoteCopyResponse(BaseModel):
    itinerary: ItineraryResponse
    source_post_id: str
    idempotent: bool


def uuid4_header(value: str) -> str:
    return validate_uuid_v4(value, "X-Operation-ID")
