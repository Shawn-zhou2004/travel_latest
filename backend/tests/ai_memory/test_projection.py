from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.modules.ai_memory.projection import ExplicitMemorySource, MemoryProjectionService
from app.modules.ai_rag.types import IngestionResult, KnowledgeChunk, KnowledgeDomain, ReviewedKnowledgeDocument


class CaptureIngestion:
    def __init__(self) -> None:
        self.documents: list[ReviewedKnowledgeDocument] = []

    async def ingest(self, document: ReviewedKnowledgeDocument) -> IngestionResult:
        self.documents.append(document)
        return IngestionResult(document_id=document.document_id, chunks_indexed=1, content_hash="hash")


class CaptureDeletion:
    def __init__(self) -> None:
        self.document_ids: list[str] = []

    async def delete_document(self, document_id: str) -> None:
        self.document_ids.append(document_id)


def explicit_memory() -> ExplicitMemorySource:
    return ExplicitMemorySource(
        memory_id="memory-1",
        user_id="user-1",
        memory_key="diet",
        memory_value={"preference": "vegetarian"},
        updated_at=datetime(2026, 8, 7, tzinfo=UTC),
    )


@pytest.mark.anyio
async def test_explicit_memory_projects_to_its_private_user_domain() -> None:
    ingestion = CaptureIngestion()
    service = MemoryProjectionService(ingestion, CaptureDeletion())

    result = await service.project(explicit_memory())

    assert result.document_id == "memory-1"
    document = ingestion.documents[0]
    assert document.document_id == "memory-1"
    assert document.source_id == "memory-1"
    assert document.knowledge_domain is KnowledgeDomain.USER_MEMORY
    assert document.visibility == "private"
    assert document.user_id == "user-1"
    assert document.city_code is None
    assert document.poi_id is None
    assert KnowledgeChunk.from_document(document, index=0, page_content=document.text).metadata.user_id == "user-1"


@pytest.mark.anyio
async def test_explicit_memory_projection_contains_only_memory_key_and_value() -> None:
    ingestion = CaptureIngestion()
    service = MemoryProjectionService(ingestion, CaptureDeletion())
    memory = ExplicitMemorySource(
        memory_id="memory-1",
        user_id="user-1",
        memory_key="diet",
        memory_value={"preference": "vegetarian"},
        updated_at=datetime(2026, 8, 7, tzinfo=UTC),
    )

    await service.project(memory)

    assert json.loads(ingestion.documents[0].text) == {
        "key": "diet",
        "value": {"preference": "vegetarian"},
    }
    assert "user-1" not in ingestion.documents[0].text
    assert "confidence" not in ingestion.documents[0].text
    assert "source" not in ingestion.documents[0].text


@pytest.mark.anyio
async def test_explicit_memory_deletion_removes_only_its_document() -> None:
    deletion = CaptureDeletion()
    service = MemoryProjectionService(CaptureIngestion(), deletion)

    await service.delete(explicit_memory())

    assert deletion.document_ids == ["memory-1"]
