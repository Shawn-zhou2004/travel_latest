from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]


class MessageCreateRequest(BaseModel):
    role: Literal["user"]
    content: dict[str, Any] = Field(min_length=1)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=128)


class MessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: dict[str, Any]
    client_message_id: str | None
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]


class AssistantAskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    client_message_id: str = Field(min_length=1, max_length=128)


class AssistantAskResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse


class MemoryResponse(BaseModel):
    id: str
    memory_type: Literal["profile", "episodic"]
    memory_key: str
    memory_value: dict[str, Any]
    source: str
    confidence: float
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]


class MemoryCreateRequest(BaseModel):
    memory_type: Literal["profile", "episodic"]
    memory_key: str = Field(min_length=1, max_length=200)
    memory_value: dict[str, Any] = Field(min_length=1)
    source: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)


class MemoryUpdateRequest(BaseModel):
    memory_value: dict[str, Any] = Field(min_length=1)
    source: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)
