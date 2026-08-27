from datetime import date, datetime
from decimal import Decimal

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


COMPANION_INTEREST_TAGS = frozenset({
    "citywalk", "food", "photography", "hiking", "museums", "nature", "history", "nightlife",
})


class PostCreate(BaseModel):
    content_type: Literal["note"] = "note"
    title: str = Field(min_length=1, max_length=200)
    body_text: str = Field(default="", max_length=20000)
    city_code: str | None = Field(default=None, max_length=32)


class FieldNoteCreate(BaseModel):
    version_no: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    recap_text: str = Field(min_length=1, max_length=20_000)
    cover_media_id: str
    media_ids: list[str] = Field(min_length=1, max_length=9)


class ModerationDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReactionCreate(BaseModel):
    reaction_type: str = Field(default="like", max_length=24)


class CompanionApplicationCreate(BaseModel):
    message: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_message(self) -> "CompanionApplicationCreate":
        if not self.message.strip():
            raise ValueError("message must not be blank.")
        return self


class CompanionApplicationAcceptRequest(BaseModel):
    group_name: str | None = Field(default=None, max_length=200)
    group_avatar_asset_id: str | None = Field(default=None, max_length=36)


class CompanionRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    city_code: str | None = Field(default=None, max_length=32)
    description: str = Field(min_length=1, max_length=10000)


class CompanionPlanCreate(BaseModel):
    city_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    party_size: int = Field(ge=2, le=12)
    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    travel_pace: Literal["slow", "balanced", "packed"]
    interest_tags: list[str] = Field(min_length=1, max_length=8)
    intro_text: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_publish_metadata(self) -> "CompanionPlanCreate":
        if (self.budget_min is None) != (self.budget_max is None):
            raise ValueError("budget_min and budget_max must be provided together.")
        if self.budget_min is not None and self.budget_min > self.budget_max:
            raise ValueError("budget_min must not exceed budget_max.")
        if (self.budget_min is None) != (self.currency is None):
            raise ValueError("currency is required exactly when a budget range is provided.")
        if len(set(self.interest_tags)) != len(self.interest_tags) or any(tag not in COMPANION_INTEREST_TAGS for tag in self.interest_tags):
            raise ValueError("interest_tags contains an unsupported or duplicate tag.")
        return self


class CompanionActivityCreate(CompanionPlanCreate):
    title: str = Field(min_length=1, max_length=200)
    city_code: str = Field(min_length=1, max_length=32)
    activity_date: date
    starts_at: datetime
    ends_at: datetime
    poi_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_activity_time_range(self) -> "CompanionActivityCreate":
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be earlier than ends_at.")
        if self.starts_at.date() != self.activity_date or self.ends_at.date() != self.activity_date:
            raise ValueError("Activity times must fall on activity_date.")
        return self


class CompanionRequestUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    city_code: str | None = Field(default=None, max_length=32)
    party_size: int | None = Field(default=None, ge=2, le=12)
    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    travel_pace: Literal["slow", "balanced", "packed"] | None = None
    interest_tags: list[str] | None = Field(default=None, min_length=1, max_length=8)
    intro_text: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_interest_tags(self) -> "CompanionRequestUpdate":
        if self.interest_tags is not None and (
            len(set(self.interest_tags)) != len(self.interest_tags)
            or any(tag not in COMPANION_INTEREST_TAGS for tag in self.interest_tags)
        ):
            raise ValueError("interest_tags contains an unsupported or duplicate tag.")
        return self


class CompanionRequestResponse(BaseModel):
    id: str
    owner_id: str
    title: str
    city_code: str | None
    description: str
    status: str

    model_config = {"from_attributes": True}


class CompanionPlanResponse(CompanionRequestResponse):
    itinerary_id: str
    trip_kind: Literal["trip", "activity"]
    start_date: date
    end_date: date
    party_size: int
    accepted_count: int
    budget_min: Decimal | None
    budget_max: Decimal | None
    currency: str | None
    travel_pace: Literal["slow", "balanced", "packed"]
    interest_tags: list[str]
    intro_text: str
    review_status: str


class CompanionPlanSummaryResponse(BaseModel):
    id: str
    title: str
    city_code: str | None
    trip_kind: Literal["trip", "activity"] | None
    start_date: date | None
    end_date: date | None
    party_size: int | None
    accepted_count: int
    budget_min: Decimal | None
    budget_max: Decimal | None
    currency: str | None
    travel_pace: Literal["slow", "balanced", "packed"] | None
    interest_tags: list[str]
    intro_text: str | None
    route_count: int
    cover_candidate: str | None
    status: Literal["open", "full", "closed", "cancelled", "completed"]
    application_status: Literal["pending", "accepted", "rejected", "withdrawn"] | None = None
    viewer_role: Literal["owner", "member", "applicant", "public"]


class CompanionPlanMemberResponse(BaseModel):
    display_name: str | None
    avatar_asset_id: str | None
    role: Literal["owner", "member"]


class CompanionPlanDetailResponse(CompanionPlanSummaryResponse):
    review_status: Literal["pending_review", "approved", "rejected"] | None = None
    members: list[CompanionPlanMemberResponse] = Field(default_factory=list)
    itinerary_id: str | None = None
    conversation_id: str | None = None
    protected_itinerary: dict[str, Any] | None = None


class CompanionPlanPage(BaseModel):
    items: list[CompanionPlanSummaryResponse]
    next_cursor: str | None = None


class CompanionApplicationResponse(BaseModel):
    id: str
    request_id: str
    applicant_id: str
    message: str
    status: str
    conversation_id: str | None = None
    applicant_display_name: str | None = None

    model_config = {"from_attributes": True}


class CompanionApplicationAcceptanceResponse(BaseModel):
    application: CompanionApplicationResponse
    conversation_id: str
    group_name: str | None
    group_avatar_asset_id: str | None
    plan_status: Literal["open", "full", "closed", "cancelled", "completed"]
    accepted_count: int


class CommentCreate(BaseModel):
    body_text: str = Field(min_length=1, max_length=10000)
    parent_id: str | None = None


class ReportCreate(BaseModel):
    reason_code: str = Field(min_length=1, max_length=64)
    detail: str | None = Field(default=None, max_length=500)


class PostResponse(BaseModel):
    id: str
    author_id: str
    title: str
    body_text: str
    city_code: str | None
    status: str
    published_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class FieldNoteResponse(PostResponse):
    recap_text: str
    itinerary_snapshot: dict[str, Any]
    cover_media_id: str | None
    media_ids: list[str]
    day_count: int
    stop_count: int
    copy_count: int


class FieldNotePage(BaseModel):
    items: list[FieldNoteResponse]
    next_cursor: str | None = None


class FieldNoteAuthorResponse(FieldNoteResponse):
    moderation_reason: str | None = None


class PostPage(BaseModel):
    items: list[PostResponse]
    next_cursor: str | None = None


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    post_id: str
    author_id: str
    parent_id: str | None
    body_text: str
    created_at: datetime


class CommentPage(BaseModel):
    items: list[CommentResponse]
    next_cursor: str | None = None


class InteractionResponse(BaseModel):
    id: str
    post_id: str
    created_at: datetime


class FollowResponse(BaseModel):
    user_id: str
    created_at: datetime


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    target_type: Literal["post", "comment"]
    target_id: str
    status: Literal["pending", "resolved", "dismissed"]
    created_at: datetime
