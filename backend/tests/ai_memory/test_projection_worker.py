from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.ai_memory.projection import ExplicitMemorySource
from app.modules.ai_memory.projection import MemoryProjectionService
from app.modules.ai_memory.projection_worker import MemoryProjectionWorker
from app.modules.ai_rag.types import AuthorityLevel, IngestionResult, KnowledgeSourceType, ReviewedKnowledgeDocument


class FakeConnection:
    def __init__(self, rows: list[Mapping[str, object] | None]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrows: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append((query, args))
        return "DELETE 1"

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        self.fetchrows.append((query, args))
        return self.rows.pop(0) if self.rows else None

    @asynccontextmanager
    async def transaction(self):
        yield self


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class CaptureProjection:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.projected: list[str] = []

    async def delete(self, memory: ExplicitMemorySource) -> None:
        self.deleted.append(memory.memory_id)

    async def project(self, memory: ExplicitMemorySource) -> None:
        self.projected.append(memory.memory_id)


class CaptureIngestion:
    def __init__(self) -> None:
        self.document: ReviewedKnowledgeDocument | None = None

    async def ingest(self, document: ReviewedKnowledgeDocument) -> IngestionResult:
        self.document = document
        return IngestionResult(document_id=document.document_id, chunks_indexed=1, content_hash="hash")


def task(version: int = 1) -> Mapping[str, object]:
    return {
        "id": "task-1", "memory_id": "memory-1", "user_id": "user-1",
        "projection_version": version, "lease_token": "lease-1", "attempt_count": 1,
    }


def source(*, version: int = 1, deleted: bool = False) -> Mapping[str, object]:
    return {
        "id": "memory-1",
        "user_id": "user-1",
        "memory_key": "diet",
        "memory_value": {"preference": "vegetarian"},
        "updated_at": datetime(2026, 8, 7, tzinfo=UTC),
        "deleted_at": datetime(2026, 8, 8, tzinfo=UTC) if deleted else None,
        "projection_version": version,
    }


@pytest.mark.anyio
async def test_drain_replaces_active_memory_then_completes_task() -> None:
    connection = FakeConnection([task(), source(), None])
    projection = CaptureProjection()

    completed = await MemoryProjectionWorker(FakePool(connection), projection).drain(limit=2)

    assert completed == 1
    assert projection.deleted == ["memory-1"]
    assert projection.projected == ["memory-1"]
    assert "SET status = 'completed'" in connection.executed[0][0]
    assert connection.executed[0][1] == ("task-1", "lease-1", 1)


@pytest.mark.anyio
async def test_drain_decodes_asyncpg_json_memory_values() -> None:
    decoded_source = dict(source())
    decoded_source["memory_value"] = '{"preference":"vegetarian"}'
    connection = FakeConnection([task(), decoded_source, None])
    projection = CaptureProjection()

    completed = await MemoryProjectionWorker(FakePool(connection), projection).drain(limit=2)

    assert completed == 1
    assert projection.projected == ["memory-1"]


@pytest.mark.anyio
async def test_drain_deletes_a_soft_deleted_source() -> None:
    connection = FakeConnection([task(), source(deleted=True), None])
    projection = CaptureProjection()

    completed = await MemoryProjectionWorker(FakePool(connection), projection).drain()

    assert completed == 1
    assert projection.deleted == ["memory-1"]
    assert projection.projected == []


@pytest.mark.anyio
async def test_drain_discards_a_superseded_task_without_projecting() -> None:
    connection = FakeConnection([task(version=1), source(version=2), None])
    projection = CaptureProjection()

    completed = await MemoryProjectionWorker(FakePool(connection), projection).drain()

    assert completed == 1
    assert projection.deleted == []
    assert projection.projected == []


@pytest.mark.anyio
async def test_drain_releases_a_failed_lease_with_exponential_backoff() -> None:
    connection = FakeConnection([task(), source()])

    class FailingProjection(CaptureProjection):
        async def project(self, memory: ExplicitMemorySource) -> None:
            raise RuntimeError("index unavailable")

    completed = await MemoryProjectionWorker(
        FakePool(connection), FailingProjection(), maximum_retry_delay_seconds=60
    ).drain()

    assert completed == 0
    retry_query, retry_args = connection.executed[-1]
    assert "SET status = 'requested'" in retry_query
    assert retry_args[:2] == ("task-1", "lease-1")
    assert retry_args[2] == 1
    assert retry_args[3] == "index unavailable"


@pytest.mark.anyio
async def test_claim_query_recovers_expired_leases_and_uses_compare_and_set() -> None:
    connection = FakeConnection([task(), source()])
    projection = CaptureProjection()

    await MemoryProjectionWorker(FakePool(connection), projection).drain(limit=1)

    claim_query, claim_args = connection.fetchrows[0]
    assert "lease_expires_at <= now()" in claim_query
    assert "FOR UPDATE SKIP LOCKED" in claim_query
    assert "task.status = 'requested'" in claim_query
    assert len(claim_args) == 2


@pytest.mark.anyio
async def test_memory_document_uses_private_memory_source_metadata() -> None:
    ingestion = CaptureIngestion()
    service = MemoryProjectionService(ingestion, CaptureProjection())

    await service.project(
        ExplicitMemorySource(
            memory_id="memory-1",
            user_id="user-1",
            memory_key="diet",
            memory_value={"preference": "vegetarian"},
            updated_at=datetime(2026, 8, 7, tzinfo=UTC),
            projection_version=3,
        )
    )

    assert ingestion.document is not None
    assert ingestion.document.source_type is KnowledgeSourceType.MEMORY
    assert ingestion.document.authority_level is AuthorityLevel.PRIVATE_MEMORY
    assert ingestion.document.source_version == "3"
