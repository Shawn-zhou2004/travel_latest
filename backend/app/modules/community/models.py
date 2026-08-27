from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DECIMAL, Date, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class Post(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'pending_review', 'published', 'hidden', 'rejected')", name="ck_posts_status"),
        CheckConstraint("content_type IN ('note', 'itinerary')", name="ck_posts_content_type"),
        CheckConstraint("copy_count >= 0", name="ck_posts_copy_count_nonnegative"),
        Index("ix_posts_public_feed", "status", "city_code", "published_at"),
    )

    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(24), nullable=False, default="note")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    city_code: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    moderation_reason: Mapped[str | None] = mapped_column(String(500))
    sanitized_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    itinerary_id: Mapped[str | None] = mapped_column(ForeignKey("itineraries.id", ondelete="SET NULL"), index=True)
    itinerary_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("itinerary_versions.id", ondelete="SET NULL"), index=True
    )
    itinerary_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    recap_text: Mapped[str | None] = mapped_column(Text)
    cover_media_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"))
    copy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PostMedia(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "post_media"
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    media_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)


class PostReaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "post_reactions"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_reactions_post_user"),)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reaction_type: Mapped[str] = mapped_column(String(24), nullable=False, default="like")


class PostFavorite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "post_favorites"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_favorites_post_user"),)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)


class Follow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "followee_id", name="uq_follows_follower_followee"),
        CheckConstraint("follower_id <> followee_id", name="ck_follows_not_self"),
    )

    follower_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    followee_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)


class Comment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "comments"
    __table_args__ = (CheckConstraint("status IN ('visible', 'hidden')", name="ck_comments_status"),)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("comments.id", ondelete="SET NULL"))
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="visible")


class ContentReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_reports"
    __table_args__ = (
        CheckConstraint("target_type IN ('post', 'comment')", name="ck_content_reports_target_type"),
        CheckConstraint("status IN ('pending', 'resolved', 'dismissed')", name="ck_content_reports_status"),
    )
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    resolution: Mapped[str | None] = mapped_column(String(500))


class CompanionRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companion_requests"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'full', 'closed', 'cancelled', 'completed')", name="ck_companion_requests_status"),
        CheckConstraint("start_date IS NULL OR end_date IS NULL OR start_date <= end_date", name="ck_companion_requests_date_order"),
        CheckConstraint("party_size IS NULL OR party_size >= 2", name="ck_companion_requests_party_size"),
        CheckConstraint(
            "accepted_count >= 1 AND (party_size IS NULL OR accepted_count <= party_size)",
            name="ck_companion_requests_accepted_count",
        ),
        CheckConstraint(
            "budget_min IS NULL OR budget_max IS NULL OR budget_min <= budget_max",
            name="ck_companion_requests_budget_order",
        ),
        CheckConstraint("trip_kind IS NULL OR trip_kind IN ('trip', 'activity')", name="ck_companion_requests_trip_kind"),
        CheckConstraint(
            "travel_pace IS NULL OR travel_pace IN ('slow', 'balanced', 'packed')",
            name="ck_companion_requests_travel_pace",
        ),
        Index("ix_companion_requests_public_discovery", "review_status", "status", "start_date"),
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    city_code: Mapped[str | None] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending_review")
    review_reason: Mapped[str | None] = mapped_column(String(500))
    itinerary_id: Mapped[str | None] = mapped_column(ForeignKey("itineraries.id", ondelete="SET NULL"), index=True)
    trip_kind: Mapped[str | None] = mapped_column(String(16))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    party_size: Mapped[int | None] = mapped_column(Integer)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    budget_min: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2))
    budget_max: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    travel_pace: Mapped[str | None] = mapped_column(String(16))
    interest_tags: Mapped[list[str] | None] = mapped_column(JSON)
    intro_text: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True)


class CompanionApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companion_applications"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'withdrawn')", name="ck_companion_applications_status"),
        UniqueConstraint("request_id", "applicant_id", name="uq_companion_applications_request_applicant"),
    )
    request_id: Mapped[str] = mapped_column(ForeignKey("companion_requests.id", ondelete="CASCADE"), nullable=False)
    applicant_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
