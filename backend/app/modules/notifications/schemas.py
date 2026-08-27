from datetime import datetime

from typing import Any

from pydantic import BaseModel, Field

from app.modules.chat.schemas import MessageResponse


class NotificationResponse(BaseModel):
    id: str
    notification_type: str
    created_at: datetime
    read_at: datetime | None
    payload: dict[str, Any]


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    next_cursor: str | None = None


class NotificationMarkReadRequest(BaseModel):
    notification_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)


class NotificationMarkReadResponse(BaseModel):
    updated_count: int


class GroupUnreadSummary(BaseModel):
    conversation_id: str
    title: str
    avatar_asset_id: str | None
    unread_count: int
    last_message: MessageResponse | None


class UnreadSummaryResponse(BaseModel):
    groups: list[GroupUnreadSummary]
    total_unread: int
