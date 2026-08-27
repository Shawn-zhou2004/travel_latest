from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now
import app.modules.community.models  # noqa: F401


class AdminAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "admin_actions"

    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


class SearchIndexRebuildJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "search_index_rebuild_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_search_index_rebuild_status"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_search_index_rebuild_progress"),
        Index("ix_search_index_rebuild_index_status", "index_name", "status"),
        UniqueConstraint("active_key", name="uq_search_index_rebuild_active_key"),
    )

    index_name: Mapped[str] = mapped_column(String(64), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(64))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    progress: Mapped[int] = mapped_column(nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class OfficialKnowledgeSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reviewed public material eligible for the shared travel RAG corpus."""

    __tablename__ = "official_knowledge_sources"
    __table_args__ = (
        CheckConstraint("source_type IN ('rule', 'template', 'poi')", name="ck_official_knowledge_source_type"),
        CheckConstraint("status IN ('draft', 'pending_review', 'indexing', 'indexed', 'removing', 'failed', 'rejected', 'inactive')", name="ck_official_knowledge_status"),
        CheckConstraint("knowledge_domain IN ('official', 'community')", name="ck_oks_domain"),
        Index("ix_oks_domain_status_city", "knowledge_domain", "status", "city_code"),
        Index("ix_oks_next_review", "next_review_at"),
        Index("ix_oks_supersedes", "supersedes_document_id"),
    )

    source_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    knowledge_domain: Mapped[str] = mapped_column(String(16), nullable=False, default="official")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    city_code: Mapped[str | None] = mapped_column(String(32), index=True)
    poi_id: Mapped[str | None] = mapped_column(String(128), index=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    review_reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_review_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False, default="1")
    supersedes_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("official_knowledge_sources.id")
    )
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    index_error: Mapped[str | None] = mapped_column(String(500))
    removal_error: Mapped[str | None] = mapped_column(String(500))


class PoiCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AMap-verified attraction discovered from a user-confirmed AI preview."""

    __tablename__ = "poi_candidates"
    __table_args__ = (
        CheckConstraint("status IN ('pending_review', 'approved', 'rejected', 'retired')", name="ck_poi_candidate_status"),
        CheckConstraint("admin_weight >= 0 AND admin_weight <= 100", name="ck_poi_candidate_admin_weight"),
        CheckConstraint("discovery_count >= 0", name="ck_poi_candidate_discovery_count"),
        CheckConstraint("confirmed_itinerary_count >= 0", name="ck_poi_candidate_confirmed_count"),
        UniqueConstraint("poi_id", name="uq_poi_candidates_poi_id"),
        Index("ix_poi_candidates_city_status_rank", "city_code", "status", "admin_weight", "confirmed_itinerary_count", "discovery_count"),
    )

    poi_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    city_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    longitude: Mapped[float] = mapped_column(nullable=False)
    latitude: Mapped[float] = mapped_column(nullable=False)
    amap_type: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", index=True)
    admin_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed_itinerary_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    official_knowledge_source_id: Mapped[str | None] = mapped_column(ForeignKey("official_knowledge_sources.id"), unique=True)


class PoiKnowledgeImportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "poi_knowledge_import_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_poi_knowledge_import_jobs_status"),
        CheckConstraint("imported_count >= 0", name="ck_poi_knowledge_import_jobs_imported_count"),
        CheckConstraint("skipped_count >= 0", name="ck_poi_knowledge_import_jobs_skipped_count"),
    )

    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    city_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    imported_count: Mapped[int] = mapped_column(nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500))


class StructuredKnowledgeImportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "structured_knowledge_import_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_structured_knowledge_import_jobs_status"),
        CheckConstraint("imported_count >= 0", name="ck_structured_knowledge_import_jobs_imported_count"),
        CheckConstraint("skipped_count >= 0", name="ck_structured_knowledge_import_jobs_skipped_count"),
    )

    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    city_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entries: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    imported_count: Mapped[int] = mapped_column(nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500))


class WebKnowledgeSearchJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An administrator-requested discovery run; retrieved bodies are never persisted here."""

    __tablename__ = "web_knowledge_search_jobs"
    __table_args__ = (
        CheckConstraint("target_domain IN ('official', 'community')", name="ck_web_knowledge_search_jobs_target_domain"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_web_knowledge_search_jobs_status"),
        CheckConstraint("result_count >= 0", name="ck_web_knowledge_search_jobs_result_count"),
    )

    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    city_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    target_domain: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    provider_name: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    result_count: Mapped[int] = mapped_column(nullable=False, default=0)


class WebKnowledgeCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Metadata from a web-search result awaiting administrator review."""

    __tablename__ = "web_knowledge_candidates"
    __table_args__ = (
        CheckConstraint("target_domain IN ('official', 'community')", name="ck_web_knowledge_candidates_target_domain"),
        CheckConstraint(
            "status IN ('needs_human_review', 'approved', 'rejected', 'ingested', 'failed')",
            name="ck_web_knowledge_candidates_status",
        ),
        UniqueConstraint("job_id", "source_url_hash", name="uq_web_knowledge_candidates_job_source_url_hash"),
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("status", "needs_human_review")
        source_url = kwargs.get("source_url")
        if isinstance(source_url, str):
            kwargs.setdefault("source_url_hash", sha256(source_url.encode("utf-8")).hexdigest())
        super().__init__(**kwargs)

    job_id: Mapped[str] = mapped_column(ForeignKey("web_knowledge_search_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(4000), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_host: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    excerpt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    city_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_domain: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_human_review", index=True)
    review_reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    external_web_source_id: Mapped[str | None] = mapped_column(ForeignKey("external_web_knowledge_sources.id"), unique=True)


class ExternalWebKnowledgeSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Administrator-edited source material derived from one reviewed web candidate."""

    __tablename__ = "external_web_knowledge_sources"
    __table_args__ = (
        CheckConstraint("target_domain IN ('official', 'community')", name="ck_external_web_knowledge_sources_target_domain"),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'indexing', 'indexed', 'removing', 'failed', 'rejected', 'inactive')",
            name="ck_external_web_knowledge_sources_status",
        ),
        UniqueConstraint("candidate_id", name="uq_external_web_knowledge_sources_candidate_id"),
    )

    candidate_id: Mapped[str] = mapped_column(ForeignKey("web_knowledge_candidates.id"), nullable=False)
    target_domain: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    city_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_host: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", index=True)
    review_reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    index_error: Mapped[str | None] = mapped_column(String(500))
    removal_error: Mapped[str | None] = mapped_column(String(500))


class CommunityKnowledgeReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The durable knowledge-review decision for one community post."""

    __tablename__ = "community_knowledge_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_ckr_status",
        ),
        UniqueConstraint("post_id", name="uq_ckr_post"),
        Index("ix_ckr_status_created", "status", "created_at"),
        Index("ix_ckr_reviewer_reviewed", "reviewed_by", "reviewed_at"),
    )

    post_id: Mapped[str] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
