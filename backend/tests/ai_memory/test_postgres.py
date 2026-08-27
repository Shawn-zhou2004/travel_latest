from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.ai_memory.postgres import AIMemoryRepository, SCHEMA_SQL
from app.modules.ai_workflows.contracts import Citation, GenerationRequest, VerifiedItineraryDraft


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fetches: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrows: list[tuple[str, tuple[object, ...]]] = []
        self.rows: list[Mapping[str, object] | None] = []
        self.results: list[str] = []
        self.fetched: list[Sequence[Mapping[str, object]]] = []
        self.transaction_entries = 0

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append((query, args))
        return self.results.pop(0) if self.results else "UPDATE 0"

    async def fetch(self, query: str, *args: object) -> Sequence[Mapping[str, object]]:
        self.fetches.append((query, args))
        return self.fetched.pop(0) if self.fetched else []

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        self.fetchrows.append((query, args))
        return self.rows.pop(0) if self.rows else None

    @asynccontextmanager
    async def transaction(self):
        self.transaction_entries += 1
        yield self


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def test_projection_task_schema_has_additive_retry_and_lease_state() -> None:
    assert "ADD COLUMN IF NOT EXISTS lease_token TEXT" in SCHEMA_SQL
    assert "ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ" in SCHEMA_SQL
    assert "ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0" in SCHEMA_SQL
    assert "ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT now()" in SCHEMA_SQL
    assert "ADD COLUMN IF NOT EXISTS last_error TEXT" in SCHEMA_SQL
    assert "ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ" in SCHEMA_SQL
    assert "status IN ('requested', 'leased', 'completed')" in SCHEMA_SQL
    assert "ix_ai_memory_projection_tasks_lease_expiry" in SCHEMA_SQL
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_memories_active_travel_profile" in SCHEMA_SQL
    assert "WHERE deleted_at IS NULL AND memory_type = 'profile' AND memory_key = 'travel_profile'" in SCHEMA_SQL


@pytest.mark.anyio
async def test_create_assistant_run_persists_user_message_in_the_same_transaction() -> None:
    connection = FakeConnection()
    connection.rows.extend((None, {
        "id": "user-message-1", "role": "user", "content": {"text": "hello"},
        "client_message_id": "client-1", "created_at": datetime.now(UTC),
    }, {"id": "run-1", "status": "queued"}))
    repository = AIMemoryRepository(FakePool(connection))

    run = await repository.create_assistant_run("owner-1", "conversation-1", "client-1", "hello")

    assert run is not None
    assert connection.transaction_entries == 1
    assert len(connection.fetchrows) == 3
    assert "INSERT INTO ai_messages" in connection.fetchrows[1][0]
    assert "INSERT INTO ai_assistant_runs" in connection.fetchrows[2][0]


@pytest.mark.anyio
async def test_append_message_scopes_owner_and_returns_existing_idempotent_message() -> None:
    connection = FakeConnection()
    created_at = datetime.now(UTC)
    connection.rows.append({
        "id": "message-1", "role": "user", "content": {"text": "hello"},
        "client_message_id": "client-1", "created_at": created_at,
    })
    repository = AIMemoryRepository(FakePool(connection))

    message = await repository.append_message("owner-1", "conversation-1", "user", {"text": "hello"}, "client-1")

    assert message is not None
    assert message["id"] == "message-1"
    query, args = connection.fetchrows[0]
    assert "WHERE id = $6 AND user_id = $2" in query
    assert "ON CONFLICT (conversation_id, user_id, client_message_id)" in query
    assert args[1] == "owner-1"
    assert args[5] == "conversation-1"


@pytest.mark.anyio
async def test_delete_conversation_is_scoped_to_its_owner() -> None:
    connection = FakeConnection()
    connection.results.append("DELETE 1")
    repository = AIMemoryRepository(FakePool(connection))

    deleted = await repository.delete_conversation("owner-1", "conversation-1")

    assert deleted is True
    query, args = connection.executed[0]
    assert "DELETE FROM ai_conversations" in query
    assert args == ("conversation-1", "owner-1")


@pytest.mark.anyio
async def test_memory_queries_are_owner_scoped_and_soft_delete() -> None:
    connection = FakeConnection()
    connection.rows.append({"projection_version": 2})
    repository = AIMemoryRepository(FakePool(connection))

    deleted = await repository.delete_memory("owner-1", "memory-1")
    await repository.list_memories("owner-1")
    await repository.get_memory("owner-1", "memory-1")

    assert deleted is True
    delete_query, delete_args = connection.fetchrows[0]
    assert "deleted_at = now()" in delete_query
    assert "projection_version = projection_version + 1" in delete_query
    assert "WHERE id = $2 AND user_id = $1 AND deleted_at IS NULL" in delete_query
    assert delete_args == ("owner-1", "memory-1")
    task_query, task_args = connection.executed[0]
    assert "INSERT INTO ai_memory_projection_tasks" in task_query
    assert task_args[1:] == ("memory-1", "owner-1", 2, "delete")
    assert connection.fetches[0][1] == ("owner-1",)
    assert "deleted_at IS NULL" in connection.fetches[0][0]
    assert connection.fetchrows[1][1] == ("memory-1", "owner-1")


@pytest.mark.anyio
async def test_update_memory_returns_only_the_owned_active_memory() -> None:
    connection = FakeConnection()
    updated_at = datetime.now(UTC)
    connection.rows.append({
        "id": "memory-1", "memory_type": "profile", "memory_key": "diet",
        "memory_value": {"preference": "vegetarian"}, "source": "user", "confidence": 1.0,
        "created_at": updated_at, "updated_at": updated_at, "projection_version": 2,
    })
    repository = AIMemoryRepository(FakePool(connection))

    memory = await repository.update_memory(
        "owner-1", "memory-1", {"preference": "vegetarian"}, "user", 1.0
    )

    assert memory is not None
    query, args = connection.fetchrows[0]
    assert "RETURNING id, memory_type" in query
    assert "projection_version = projection_version + 1" in query
    assert "WHERE id = $2 AND user_id = $1 AND deleted_at IS NULL" in query
    assert args[:2] == ("owner-1", "memory-1")
    task_query, task_args = connection.executed[0]
    assert "INSERT INTO ai_memory_projection_tasks" in task_query
    assert task_args[1:] == ("memory-1", "owner-1", 2, "upsert")


@pytest.mark.anyio
async def test_create_memory_enqueues_an_initial_upsert_in_the_same_transaction() -> None:
    connection = FakeConnection()
    repository = AIMemoryRepository(FakePool(connection))

    memory_id = await repository.create_memory(
        "owner-1", "profile", "diet", {"preference": "vegetarian"}, "user", 1.0
    )

    assert connection.transaction_entries == 1
    source_query, source_args = connection.executed[0]
    task_query, task_args = connection.executed[1]
    assert "INSERT INTO ai_memories" in source_query
    assert source_args[0] == memory_id
    assert "INSERT INTO ai_memory_projection_tasks" in task_query
    assert task_args[1:] == (memory_id, "owner-1", 1, "upsert")


@pytest.mark.anyio
async def test_upsert_profile_memory_updates_same_key_and_enqueues_new_version() -> None:
    connection = FakeConnection()
    connection.rows.append({
        "id": "memory-1", "memory_type": "profile", "memory_key": "travel_profile",
        "memory_value": {"travel_pace": "packed"}, "source": "user_settings", "confidence": 1.0,
        "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC), "projection_version": 2,
    })
    repository = AIMemoryRepository(FakePool(connection))

    memory = await repository.upsert_profile_memory(
        "owner-1", "travel_profile", {"travel_pace": "packed"}, "user_settings", 1.0
    )

    assert memory["id"] == "memory-1"
    assert connection.transaction_entries == 1
    query, args = connection.fetchrows[0]
    assert "ON CONFLICT (user_id)" in query
    assert "projection_version = ai_memories.projection_version + 1" in query
    assert "FOR UPDATE" not in query
    assert args[1:3] == ("owner-1", "travel_profile")
    assert connection.executed[0][1][1:] == ("memory-1", "owner-1", 2, "upsert")


@pytest.mark.anyio
async def test_upsert_profile_memory_creates_and_enqueues_initial_version() -> None:
    connection = FakeConnection()
    created_at = datetime.now(UTC)
    connection.rows.append({
        "id": "memory-1", "memory_type": "profile", "memory_key": "travel_profile",
        "memory_value": {"travel_pace": "balanced"}, "source": "user_settings", "confidence": 1.0,
        "created_at": created_at, "updated_at": created_at, "projection_version": 1,
    })
    repository = AIMemoryRepository(FakePool(connection))

    memory = await repository.upsert_profile_memory(
        "owner-1", "travel_profile", {"travel_pace": "balanced"}, "user_settings", 1.0
    )

    assert memory["id"] == "memory-1"
    assert connection.transaction_entries == 1
    query, _ = connection.fetchrows[0]
    assert "INSERT INTO ai_memories" in query
    assert "ON CONFLICT (user_id)" in query
    assert connection.executed[0][1][1:] == ("memory-1", "owner-1", 1, "upsert")


@pytest.mark.anyio
async def test_preview_persists_live_source_type_without_raw_url_or_page_body() -> None:
    connection = FakeConnection()
    connection.rows.extend(({"id": "preview-1"}, {
        "id": "preview-1", "generation_job_id": "job-1", "draft": {"title": "Trip", "days": []},
        "prompt_version": None, "model_version": None, "created_at": datetime.now(UTC),
        "target_itinerary_id": None, "base_version": None,
    }))
    connection.fetched.append(({
        "document_id": "live-web:digest", "chunk_id": "live-web:digest", "source_type": "live_web",
        "source_id": "example.cn", "city_code": "430100", "source_updated_at": "2026-08-10T00:00:00+00:00",
        "content": "Yuelu Mountain\nVisit information",
    },))
    repository = AIMemoryRepository(FakePool(connection))
    today = datetime.now(UTC).date()
    request = GenerationRequest("job-1", "user-1", "Changsha", "430100", today, today)
    citation = Citation("live-web:digest", "live-web:digest", "live_web", "example.cn", "430100", "2026-08-10T00:00:00+00:00", "Yuelu Mountain\nVisit information")

    await repository.save_preview(request, VerifiedItineraryDraft("Trip", ()), (citation,), ())
    stored = await repository.get_preview("user-1", "preview-1")

    assert stored is not None
    assert stored["citations"][0]["source_type"] == "live_web"
    assert "raw_html" not in stored["citations"][0]
    assert "https://" not in stored["citations"][0]["source_id"]
    assert "WHERE id = $1 AND user_id = $2 AND state = 'preview'" in connection.fetchrows[-1][0]
    citation_insert_args = connection.executed[0][1]
    assert all("https://" not in str(value) for value in citation_insert_args)
    assert await repository.get_preview("user-2", "preview-1") is None


@pytest.mark.anyio
async def test_preview_labels_non_live_citations_as_reviewed_knowledge() -> None:
    connection = FakeConnection()
    connection.rows.append({"id": "preview-1"})
    repository = AIMemoryRepository(FakePool(connection))
    today = datetime.now(UTC).date()
    request = GenerationRequest("job-1", "user-1", "Changsha", "430100", today, today)
    citation = Citation("reviewed-1", "chunk-1", "official", "source-1", "430100", "2026-08-10T00:00:00+00:00", "Reviewed source")

    await repository.save_preview(request, VerifiedItineraryDraft("Trip", ()), (citation,), ())

    assert connection.executed[0][1][5] == "reviewed_knowledge"
