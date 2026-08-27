from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.models.outbox import ImmutableJSON


class ExportTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_tasks"
    __table_args__ = (
        CheckConstraint("format = 'docx'", name="ck_export_tasks_format"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired')", name="ck_export_tasks_status"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_export_tasks_progress"),
        CheckConstraint("attempt_count >= 0", name="ck_export_tasks_attempt_count"),
        UniqueConstraint("requester_id", "idempotency_key", name="uq_export_tasks_requester_key"),
        Index("ix_export_tasks_status_expires_at", "status", "expires_at"),
    )

    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    itinerary_id: Mapped[str] = mapped_column(ForeignKey("itineraries.id", ondelete="RESTRICT"), nullable=False, index=True)
    itinerary_version_id: Mapped[str] = mapped_column(ForeignKey("itinerary_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="docx")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(ImmutableJSON(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(500))
    trace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
