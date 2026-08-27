from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (CheckConstraint("conversation_type IN ('direct', 'companion_group')", name="ck_conversations_type"),)
    conversation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    direct_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    title: Mapped[str | None] = mapped_column(String(200))
    avatar_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True, index=True)


class ConversationMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_conversation_members_conversation_user"),)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_read_message_id: Mapped[str | None] = mapped_column(String(36))


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("message_type IN ('text', 'image', 'location', 'itinerary_card')", name="ck_messages_type"),
        UniqueConstraint("conversation_id", "sender_id", "client_message_id", name="uq_messages_conversation_sender_client_id"),
    )
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    client_message_id: Mapped[str] = mapped_column(String(80), nullable=False)
    message_type: Mapped[str] = mapped_column(String(24), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class UserBlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_blocks"
    __table_args__ = (
        CheckConstraint("blocker_id <> blocked_id", name="ck_user_blocks_distinct_users"),
        UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocks_blocker_blocked"),
    )
    blocker_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    blocked_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
