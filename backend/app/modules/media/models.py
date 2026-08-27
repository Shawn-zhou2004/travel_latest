from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class MediaAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'expired') "
            "AND (status != 'pending' OR upload_expires_at IS NOT NULL)",
            name="ck_media_assets_status",
        ),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document')",
            name="ck_media_assets_mime_type",
        ),
        CheckConstraint("size_bytes > 0", name="ck_media_assets_size_bytes"),
        Index("ix_media_assets_status_upload_expires_at", "status", "upload_expires_at"),
    )

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    upload_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    etag: Mapped[str | None] = mapped_column(String(128))
