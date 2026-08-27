from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class Provider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "providers"
    __table_args__ = (CheckConstraint("status IN ('pending_review', 'approved', 'rejected')", name="ck_providers_status"),)

    applicant_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact: Mapped[str] = mapped_column(String(160), nullable=False)
    qualification_asset_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    claimed_poi_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", index=True)
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ProviderReview(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "provider_reviews"

    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    previous_status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


class Experience(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "experience_services"
    __table_args__ = (CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_experience_services_status"),)

    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    poi_id: Mapped[str] = mapped_column(String(128), nullable=False)
    poi_name: Mapped[str] = mapped_column(String(160), nullable=False)
    poi_address: Mapped[str] = mapped_column(String(255), nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cancellation_policy: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)


class ExperienceSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "experience_sessions"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_experience_sessions_capacity"),
        CheckConstraint("reserved_count >= 0 AND reserved_count <= capacity", name="ck_experience_sessions_reserved_count"),
        CheckConstraint("status IN ('scheduled', 'cancelled', 'completed')", name="ck_experience_sessions_status"),
    )

    experience_id: Mapped[str] = mapped_column(ForeignKey("experience_services.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")


class ExperienceBooking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "experience_bookings"
    __table_args__ = (
        UniqueConstraint("experience_session_id", "user_id", name="uq_experience_bookings_session_user"),
        CheckConstraint("traveler_count > 0", name="ck_experience_bookings_travelers"),
        CheckConstraint("status IN ('reserved', 'verified', 'cancelled')", name="ck_experience_bookings_status"),
    )

    experience_session_id: Mapped[str] = mapped_column(ForeignKey("experience_sessions.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    traveler_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved", index=True)
    verification_code: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ExperienceReview(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "experience_reviews"
    __table_args__ = (UniqueConstraint("booking_id", name="uq_experience_reviews_booking"), CheckConstraint("rating BETWEEN 1 AND 5", name="ck_experience_reviews_rating"))

    booking_id: Mapped[str] = mapped_column(ForeignKey("experience_bookings.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
