from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.ai_rag.types import (
    AuthorityLevel,
    IngestionResult,
    KnowledgeDomain,
    KnowledgeSourceType,
    ReviewedKnowledgeDocument,
)


class MemoryDocumentIngestion(Protocol):
    async def ingest(self, document: ReviewedKnowledgeDocument) -> IngestionResult: ...


class MemoryDocumentDeletion(Protocol):
    async def delete_document(self, document_id: str) -> None: ...


@dataclass(frozen=True)
class ExplicitMemorySource:
    """A memory record deliberately saved by, and scoped to, one user."""

    memory_id: str
    user_id: str
    memory_key: str
    memory_value: Mapping[str, object]
    updated_at: datetime
    projection_version: int = 1

    def __post_init__(self) -> None:
        if not self.memory_id or not self.user_id or not self.memory_key:
            raise ValueError("explicit memory id, user id, and key are required")
        if self.updated_at.tzinfo is None:
            raise ValueError("explicit memory updated_at must be timezone-aware")
        if self.projection_version < 1:
            raise ValueError("explicit memory projection version must be positive")


class MemoryProjectionService:
    """Projects explicit user memories into the private RAG domain only."""

    def __init__(self, ingestion: MemoryDocumentIngestion, deletion: MemoryDocumentDeletion) -> None:
        self._ingestion = ingestion
        self._deletion = deletion

    async def project(self, memory: ExplicitMemorySource) -> IngestionResult:
        return await self._ingestion.ingest(
            ReviewedKnowledgeDocument(
                document_id=memory.memory_id,
                source_type=KnowledgeSourceType.MEMORY,
                source_id=memory.memory_id,
                text=json.dumps(
                    {"key": memory.memory_key, "value": dict(memory.memory_value)},
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                city_code=None,
                poi_id=None,
                language="zh-CN",
                visibility="private",
                status="reviewed",
                source_updated_at=memory.updated_at,
                knowledge_domain=KnowledgeDomain.USER_MEMORY,
                authority_level=AuthorityLevel.PRIVATE_MEMORY,
                source_version=str(memory.projection_version),
                user_id=memory.user_id,
            )
        )

    async def delete(self, memory: ExplicitMemorySource) -> None:
        await self._deletion.delete_document(memory.memory_id)
