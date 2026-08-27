from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DirectConversationCreate(BaseModel):
    user_id: str


class MessageCreate(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=80)
    message_type: str
    body_text: str | None = Field(default=None, max_length=20000)
    payload_json: dict[str, Any] | None = None


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    client_message_id: str
    message_type: str
    body_text: str | None
    payload_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BlockCreate(BaseModel):
    user_id: str


class ConversationResponse(BaseModel):
    id: str
    conversation_type: str
    title: str | None
    avatar_asset_id: str | None
    unread_count: int
    last_message: MessageResponse | None


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    next_cursor: str | None = None


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    next_cursor: str | None = None
