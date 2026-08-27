from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class GenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'understanding', 'resolving_destination', 'retrieving', 'retrieving_reviewed_sources', 'searching_live_sources', 'verifying_pois', 'planning', 'validating', 'awaiting_confirmation', 'succeeded', 'failed', 'cancelled')",
            name="ck_generation_jobs_status",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('preview', 'no_result', 'clarification', 'unavailable')",
            name="ck_generation_jobs_outcome",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_generation_jobs_progress"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_generation_jobs_user_key"),
        CheckConstraint("attempt_count >= 0", name="ck_generation_jobs_attempt_count"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    target_itinerary_id: Mapped[str | None] = mapped_column(ForeignKey("itineraries.id", ondelete="SET NULL"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    city_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(String(2000), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str | None] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str | None] = mapped_column(String(500))
    preview_id: Mapped[str | None] = mapped_column(String(36), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(500))
    trace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
