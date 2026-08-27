from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class SearchProjection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "search_projections"
    __table_args__ = (UniqueConstraint("document_type", "document_id", name="uq_search_projections_document"),)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    unavailable_reason: Mapped[str | None] = mapped_column(String(200))
