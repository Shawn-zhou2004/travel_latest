from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


PlanningPreferenceTag = Literal["经典必玩", "吃吃喝喝", "小众探索", "拍照出片", "逛街购物", "citywalk", "自然风光", "文艺展览", "历史古建"]


class PoiCandidateDecision(BaseModel):
    status: Literal["approved", "rejected", "retired"]
    tags: list[PlanningPreferenceTag] = Field(default_factory=list, max_length=9)
    admin_weight: int = Field(default=0, ge=0, le=100)
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_decision(self) -> "PoiCandidateDecision":
        self.tags = list(dict.fromkeys(self.tags))
        self.reason = self.reason.strip() if self.reason else None
        if self.status == "approved" and not self.tags:
            raise ValueError("An approved POI candidate requires at least one tag.")
        if self.status in {"rejected", "retired"} and not self.reason:
            raise ValueError("A rejection or retirement reason is required.")
        return self


class PoiCandidateResponse(BaseModel):
    id: str
    poi_id: str
    name: str
    address: str
    city_code: str
    longitude: float
    latitude: float
    amap_type: str | None
    tags: list[PlanningPreferenceTag]
    status: Literal["pending_review", "approved", "rejected", "retired"]
    admin_weight: int
    discovery_count: int
    confirmed_itinerary_count: int
    review_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    official_knowledge_source_id: str | None
    created_at: datetime
    updated_at: datetime


class SearchIndexInventoryItem(BaseModel):
    logical_name: str
    index_name: str
    status: Literal["healthy", "empty", "unavailable", "degraded"]
    document_count: int | None
    message: str | None = None


class SearchIndexInventoryResponse(BaseModel):
    items: list[SearchIndexInventoryItem]


class SearchIndexRebuildCreate(BaseModel):
    index_name: str = Field(min_length=1, max_length=64)


class SearchIndexRebuildJobResponse(BaseModel):
    id: str
    index_name: str
    requested_by: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: int
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AdminUserResponse(BaseModel):
    id: str
    phone_masked: str
    nickname: str | None
    status: Literal["active", "suspended"]
    roles: list[str]
    provider_memberships: list[str]
    created_at: datetime
    updated_at: datetime


class AdminUserPage(BaseModel):
    items: list[AdminUserResponse]
    next_cursor: str | None = None


class AdminUserUpdate(BaseModel):
    status: Literal["active", "suspended"] | None = None
    roles: list[Literal["user", "platform_admin", "provider_admin", "provider_staff"]] | None = Field(
        default=None, max_length=4
    )

    @model_validator(mode="after")
    def validate_update(self) -> "AdminUserUpdate":
        if self.status is None and self.roles is None:
            raise ValueError("At least one user status or role change is required.")
        if self.roles is not None:
            self.roles = list(dict.fromkeys(self.roles))
        return self


class WebKnowledgeSearchJobCreate(BaseModel):
    city_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    query: str = Field(min_length=1, max_length=500)
    target_domain: Literal["official", "community"]

    def model_post_init(self, __context: object) -> None:
        self.query = self.query.strip()
        if not self.query:
            raise ValueError("A search query is required.")


class WebKnowledgeCandidateDecision(BaseModel):
    status: Literal["approved", "rejected"]
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body_text: str | None = Field(default=None, min_length=1, max_length=20000)
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_decision(self) -> "WebKnowledgeCandidateDecision":
        self.title = self.title.strip() if self.title else None
        self.body_text = self.body_text.strip() if self.body_text else None
        self.reason = self.reason.strip() if self.reason else None
        if self.status == "approved" and (not self.title or not self.body_text):
            raise ValueError("An approved source requires a title and body.")
        if self.status == "rejected" and not self.reason:
            raise ValueError("A rejection reason is required.")
        return self


class WebKnowledgeSearchJobResponse(BaseModel):
    id: str
    requested_by: str
    city_code: str
    query: str
    target_domain: Literal["official", "community"]
    status: Literal["queued", "running", "succeeded", "failed"]
    provider_name: str | None
    error_code: str | None
    error_message: str | None
    result_count: int
    created_at: datetime
    updated_at: datetime


class WebKnowledgeCandidateResponse(BaseModel):
    id: str
    job_id: str
    title: str
    excerpt: str
    source_url: str
    source_host: str
    published_at: datetime | None
    fetched_at: datetime | None
    city_code: str
    target_domain: Literal["official", "community"]
    status: Literal["needs_human_review", "approved", "rejected", "ingested", "failed"]
    review_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    external_web_source_id: str | None
    created_at: datetime
    updated_at: datetime


class ExternalWebKnowledgeSourceDecision(BaseModel):
    status: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_decision(self) -> "ExternalWebKnowledgeSourceDecision":
        self.reason = self.reason.strip() if self.reason else None
        if self.status == "rejected" and not self.reason:
            raise ValueError("A rejection reason is required.")
        return self


class ExternalWebKnowledgeSourceResponse(BaseModel):
    id: str
    candidate_id: str
    target_domain: Literal["official", "community"]
    title: str
    body_text: str
    city_code: str
    source_url: str
    source_host: str
    published_at: datetime | None
    fetched_at: datetime | None
    status: Literal["draft", "pending_review", "indexing", "indexed", "removing", "failed", "rejected", "inactive"]
    review_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    indexed_at: datetime | None
    index_error: str | None
    removal_error: str | None
    created_at: datetime
    updated_at: datetime


class CommunityKnowledgeReviewDecision(BaseModel):
    status: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_decision(self) -> "CommunityKnowledgeReviewDecision":
        self.reason = self.reason.strip() if self.reason else None
        if self.status == "rejected" and not self.reason:
            raise ValueError("A rejection reason is required.")
        return self


class CommunityKnowledgeReviewResponse(BaseModel):
    id: str
    post_id: str
    status: Literal["pending", "approved", "rejected"]
    reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    post_title: str
    post_body_text: str
    post_city_code: str | None
    post_status: str
