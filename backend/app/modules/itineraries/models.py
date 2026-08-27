from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, new_uuid, utc_now, validate_uuid_v4


class Itinerary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "itineraries"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_itineraries_version"),)

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    source_post_id: Mapped[str | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"), index=True)

    def __init__(self, **kwargs: Any) -> None:
        if "owner_id" in kwargs:
            kwargs["owner_id"] = validate_uuid_v4(kwargs["owner_id"], "owner_id")
        super().__init__(**kwargs)


class ItineraryDay(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "itinerary_days"
    __table_args__ = (
        UniqueConstraint("itinerary_id", "day_date", name="uq_itinerary_days_date"),
        UniqueConstraint("itinerary_id", "display_order", name="uq_itinerary_days_display_order"),
    )

    itinerary_id: Mapped[str] = mapped_column(ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True)
    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)


class ItineraryEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "itinerary_events"
    __table_args__ = (
        UniqueConstraint("day_id", "display_order", name="uq_itinerary_events_display_order"),
        CheckConstraint("display_order >= 0", name="ck_itinerary_events_display_order"),
    )

    day_id: Mapped[str] = mapped_column(ForeignKey("itinerary_days.id", ondelete="CASCADE"), nullable=False, index=True)
    poi_id: Mapped[str] = mapped_column(String(128), nullable=False)
    poi_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class ItineraryVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "itinerary_versions"
    __table_args__ = (UniqueConstraint("itinerary_id", "version", name="uq_itinerary_versions_version"),)

    itinerary_id: Mapped[str] = mapped_column(ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


class RouteSegment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "route_segments"
    __table_args__ = (UniqueConstraint("day_id", "display_order", name="uq_route_segments_display_order"),)

    day_id: Mapped[str] = mapped_column(ForeignKey("itinerary_days.id", ondelete="CASCADE"), nullable=False, index=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    travel_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    distance_meters: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    route_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RouteCalculationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "route_calculation_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'calculating', 'completed', 'failed')", name="ck_route_calculation_jobs_status"),
    )

    itinerary_id: Mapped[str] = mapped_column(ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True)
    day_id: Mapped[str] = mapped_column(ForeignKey("itinerary_days.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    error_code: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TripCollaborator(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trip_collaborators"
    __table_args__ = (
        UniqueConstraint("itinerary_id", "user_id", name="uq_trip_collaborators_user"),
        CheckConstraint("role IN ('viewer', 'editor')", name="ck_trip_collaborators_role"),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="ck_trip_collaborators_status"),
    )

    itinerary_id: Mapped[str] = mapped_column(ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


class TripShareToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trip_share_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_trip_share_tokens_hash"),)

    itinerary_id: Mapped[str] = mapped_column(ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TripOperation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "trip_operations"
    __table_args__ = (UniqueConstraint("itinerary_id", "operation_id", name="uq_trip_operations_operation"),)

    itinerary_id: Mapped[str] = mapped_column(ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


class ItineraryCopyOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "itinerary_copy_operations"
    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "source_post_id",
            "idempotency_key",
            name="uq_itinerary_copy_operations_actor_source_key",
        ),
    )

    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    itinerary_id: Mapped[str] = mapped_column(
        ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


# Alembic imports this established itinerary model module to populate metadata.
from app.modules.trip_support import models as _trip_support_models  # noqa: E402, F401
