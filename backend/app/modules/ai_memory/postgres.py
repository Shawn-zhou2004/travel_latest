from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import asyncpg
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.modules.ai_workflows.contracts import (
        Citation,
        GenerationRequest,
        NodeAudit,
        SavedPreview,
        VerifiedItineraryDraft,
    )


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ai_conversations (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_user_updated
    ON ai_conversations (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS ai_messages (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content JSONB NOT NULL,
    client_message_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ai_messages ADD COLUMN IF NOT EXISTS client_message_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_messages_client_message
    ON ai_messages (conversation_id, user_id, client_message_id)
    WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_ai_messages_conversation_created
    ON ai_messages (conversation_id, created_at, id);

CREATE TABLE IF NOT EXISTS ai_assistant_runs (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    client_message_id TEXT NOT NULL,
    user_message_id UUID NOT NULL REFERENCES ai_messages(id),
    assistant_message_id UUID REFERENCES ai_messages(id),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    source_mode TEXT CHECK (source_mode IN ('official', 'live_web')),
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (conversation_id, user_id, client_message_id)
);
CREATE INDEX IF NOT EXISTS ix_ai_assistant_runs_user_updated
    ON ai_assistant_runs (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS ai_memories (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('profile', 'episodic')),
    memory_key TEXT NOT NULL,
    memory_value JSONB NOT NULL,
    source TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    deleted_by_user_id UUID,
    CHECK ((deleted_at IS NULL) = (deleted_by_user_id IS NULL))
);
ALTER TABLE ai_memories
    ADD COLUMN IF NOT EXISTS projection_version BIGINT NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS ix_ai_memories_active_profile
    ON ai_memories (user_id, memory_key, updated_at DESC)
    WHERE deleted_at IS NULL AND memory_type = 'profile';
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_memories_active_travel_profile
    ON ai_memories (user_id)
    WHERE deleted_at IS NULL AND memory_type = 'profile' AND memory_key = 'travel_profile';
CREATE INDEX IF NOT EXISTS ix_ai_memories_deletion
    ON ai_memories (user_id, deleted_at)
    WHERE deleted_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS ai_memory_projection_tasks (
    id UUID PRIMARY KEY,
    memory_id UUID NOT NULL REFERENCES ai_memories(id),
    user_id UUID NOT NULL,
    projection_version BIGINT NOT NULL CHECK (projection_version > 0),
    operation TEXT NOT NULL CHECK (operation IN ('upsert', 'delete')),
    status TEXT NOT NULL DEFAULT 'requested'
        CONSTRAINT ck_ai_memory_projection_tasks_status
        CHECK (status IN ('requested', 'leased', 'completed')),
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT ck_ai_memory_projection_tasks_attempt_count CHECK (attempt_count >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ai_memory_projection_tasks
    ADD COLUMN IF NOT EXISTS lease_token TEXT,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS last_error TEXT,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE ai_memory_projection_tasks
    DROP CONSTRAINT IF EXISTS ai_memory_projection_tasks_status_check;
DO $$
DECLARE
    status_constraint TEXT;
BEGIN
    SELECT conname INTO status_constraint
    FROM pg_constraint
    WHERE conrelid = 'ai_memory_projection_tasks'::regclass
        AND contype = 'c'
        AND pg_get_constraintdef(oid) LIKE '%status%'
        AND pg_get_constraintdef(oid) NOT LIKE '%leased%'
        AND conname <> 'ck_ai_memory_projection_tasks_status';
    IF status_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE ai_memory_projection_tasks DROP CONSTRAINT %I', status_constraint);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ai_memory_projection_tasks'::regclass
            AND conname = 'ck_ai_memory_projection_tasks_status'
    ) THEN
        ALTER TABLE ai_memory_projection_tasks
            ADD CONSTRAINT ck_ai_memory_projection_tasks_status
            CHECK (status IN ('requested', 'leased', 'completed'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ai_memory_projection_tasks'::regclass
            AND conname = 'ck_ai_memory_projection_tasks_lease'
    ) THEN
        ALTER TABLE ai_memory_projection_tasks
            ADD CONSTRAINT ck_ai_memory_projection_tasks_lease
            CHECK ((status = 'leased') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ai_memory_projection_tasks'::regclass
            AND conname = 'ck_ai_memory_projection_tasks_attempt_count'
    ) THEN
        ALTER TABLE ai_memory_projection_tasks
            ADD CONSTRAINT ck_ai_memory_projection_tasks_attempt_count
            CHECK (attempt_count >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ai_memory_projection_tasks'::regclass
            AND conname = 'ck_ai_memory_projection_tasks_completed'
    ) THEN
        ALTER TABLE ai_memory_projection_tasks
            ADD CONSTRAINT ck_ai_memory_projection_tasks_completed
            CHECK ((status = 'completed') = (completed_at IS NOT NULL));
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_ai_memory_projection_tasks_available
    ON ai_memory_projection_tasks (available_at, created_at, id)
    WHERE status = 'requested';
CREATE INDEX IF NOT EXISTS ix_ai_memory_projection_tasks_lease_expiry
    ON ai_memory_projection_tasks (lease_expires_at)
    WHERE status = 'leased';

CREATE TABLE IF NOT EXISTS ai_generation_previews (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    generation_job_id UUID NOT NULL UNIQUE,
    draft JSONB NOT NULL,
    state TEXT NOT NULL DEFAULT 'preview' CHECK (state = 'preview'),
    prompt_version TEXT,
    model_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ai_generation_previews ADD COLUMN IF NOT EXISTS target_itinerary_id TEXT;
ALTER TABLE ai_generation_previews ADD COLUMN IF NOT EXISTS base_version INTEGER;
CREATE INDEX IF NOT EXISTS ix_ai_generation_previews_user_created
    ON ai_generation_previews (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_preview_citations (
    id UUID PRIMARY KEY,
    preview_id UUID NOT NULL REFERENCES ai_generation_previews(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    document_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    city_code TEXT NOT NULL,
    source_updated_at TEXT NOT NULL,
    content TEXT NOT NULL,
    UNIQUE (preview_id, position)
);

CREATE TABLE IF NOT EXISTS ai_preview_audits (
    id UUID PRIMARY KEY,
    preview_id UUID NOT NULL REFERENCES ai_generation_previews(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    node TEXT NOT NULL,
    status TEXT NOT NULL,
    agent_version TEXT,
    duration_ms INTEGER,
    redacted_summary TEXT,
    tool_summary JSONB,
    degradations JSONB,
    review_codes JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (preview_id, position)
);
ALTER TABLE ai_preview_audits
    ADD COLUMN IF NOT EXISTS agent_version TEXT,
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER,
    ADD COLUMN IF NOT EXISTS redacted_summary TEXT,
    ADD COLUMN IF NOT EXISTS tool_summary JSONB,
    ADD COLUMN IF NOT EXISTS degradations JSONB,
    ADD COLUMN IF NOT EXISTS review_codes JSONB;
"""


class Connection(Protocol):
    async def execute(self, query: str, *args: object) -> str: ...

    async def fetch(self, query: str, *args: object) -> Sequence[Mapping[str, object]]: ...

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None: ...

    def transaction(self) -> Any: ...


class Pool(Protocol):
    def acquire(self) -> Any: ...


def _asyncpg_dsn(dsn: str) -> str:
    """Accept the configured SQLAlchemy-style asyncpg URL without logging it."""
    if dsn.startswith("postgresql+asyncpg://"):
        return "postgresql://" + dsn.removeprefix("postgresql+asyncpg://")
    if dsn.startswith("postgres://"):
        return "postgresql://" + dsn.removeprefix("postgres://")
    if not dsn.startswith("postgresql://"):
        raise ValueError("AI_POSTGRES_DSN must use a PostgreSQL URL")
    return dsn


class AsyncpgPoolFactory:
    """Owns the pool lifecycle; callers obtain the DSN from application settings."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10) -> None:
        self._dsn = _asyncpg_dsn(dsn)
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Any | None = None

    async def open(self) -> Any:
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=self._min_size, max_size=self._max_size
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


@asynccontextmanager
async def open_langgraph_checkpointer(dsn: str) -> AsyncIterator[AsyncPostgresSaver]:
    """Create and initialize the LangGraph-owned checkpoint schema at startup."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(_asyncpg_dsn(dsn)) as checkpointer:
        await checkpointer.setup()
        yield checkpointer


@dataclass(frozen=True)
class Conversation:
    id: str
    user_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Memory:
    id: str
    user_id: str
    memory_type: str
    memory_key: str
    memory_value: Mapping[str, object]
    source: str
    confidence: float
    created_at: datetime
    updated_at: datetime


class AIMemoryRepository:
    """AI PostgreSQL storage. It never reads or mutates MySQL business records."""

    def __init__(self, pool: Pool, *, profile_confidence_threshold: float = 0.7) -> None:
        if not 0 <= profile_confidence_threshold <= 1:
            raise ValueError("profile_confidence_threshold must be between zero and one")
        self._pool = pool
        self._profile_confidence_threshold = profile_confidence_threshold

    async def setup_schema(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(SCHEMA_SQL)

    async def create_conversation(self, user_id: str, title: str | None = None) -> str:
        conversation_id = str(uuid.uuid4())
        async with self._pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO ai_conversations (id, user_id, title) VALUES ($1, $2, $3)",
                conversation_id,
                user_id,
                title,
            )
        return conversation_id

    async def list_conversations(self, user_id: str) -> Sequence[Mapping[str, object]]:
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                """
                SELECT id, title, created_at, updated_at
                FROM ai_conversations
                WHERE user_id = $1
                ORDER BY updated_at DESC, id DESC
                """,
                user_id,
            )

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        async with self._pool.acquire() as connection:
            result = await connection.execute(
                "DELETE FROM ai_conversations WHERE id = $1 AND user_id = $2", conversation_id, user_id
            )
        return result == "DELETE 1"

    async def append_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: Mapping[str, object],
        client_message_id: str | None = None,
    ) -> Mapping[str, object] | None:
        if role not in {"user", "assistant", "system", "tool"}:
            raise ValueError("role is invalid")
        message_id = str(uuid.uuid4())
        async with self._pool.acquire() as connection:
            row = await self._append_message(
                connection, message_id, user_id, conversation_id, role, content, client_message_id
            )
        return row

    async def get_message_by_client_message_id(
        self, user_id: str, conversation_id: str, client_message_id: str
    ) -> Mapping[str, object] | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(
                """
                SELECT m.id, m.role, m.content, m.client_message_id, m.created_at
                FROM ai_messages AS m
                JOIN ai_conversations AS c ON c.id = m.conversation_id
                WHERE m.conversation_id = $1 AND c.user_id = $2 AND m.client_message_id = $3
                """,
                conversation_id,
                user_id,
                client_message_id,
            )

    async def create_assistant_run(
        self, user_id: str, conversation_id: str, client_message_id: str, text: str
    ) -> Mapping[str, object] | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                existing = await connection.fetchrow(
                    """
                    SELECT id, user_message_id, assistant_message_id, status, source_mode, error_code,
                           error_message, created_at, updated_at, completed_at
                    FROM ai_assistant_runs
                    WHERE conversation_id = $1 AND user_id = $2 AND client_message_id = $3
                    """,
                    conversation_id, user_id, client_message_id,
                )
                if existing is not None:
                    return existing
                user_message = await self._append_message(
                    connection,
                    str(uuid.uuid4()),
                    user_id,
                    conversation_id,
                    "user",
                    {"text": text},
                    client_message_id,
                )
                if user_message is None:
                    return None
                run_id = str(uuid.uuid4())
                return await connection.fetchrow(
                    """
                    INSERT INTO ai_assistant_runs
                        (id, conversation_id, user_id, client_message_id, user_message_id, status)
                    VALUES ($1, $2, $3, $4, $5, 'queued')
                    RETURNING id, user_message_id, assistant_message_id, status, source_mode, error_code,
                              error_message, created_at, updated_at, completed_at
                    """,
                    run_id, conversation_id, user_id, client_message_id, user_message["id"],
                )

    async def get_assistant_run(self, user_id: str, run_id: str) -> Mapping[str, object] | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(
                """
                SELECT id, conversation_id, user_message_id, assistant_message_id, status, source_mode,
                       error_code, error_message, created_at, updated_at, completed_at,
                       message.id AS assistant_id, message.role AS assistant_role,
                       message.content AS assistant_content,
                       message.client_message_id AS assistant_client_message_id,
                       message.created_at AS assistant_created_at
                FROM ai_assistant_runs
                LEFT JOIN ai_messages AS message ON message.id = ai_assistant_runs.assistant_message_id
                WHERE ai_assistant_runs.id = $1 AND ai_assistant_runs.user_id = $2
                """,
                run_id, user_id,
            )

    async def start_assistant_run(self, user_id: str, run_id: str) -> Mapping[str, object] | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(
                """
                UPDATE ai_assistant_runs SET status = 'running', updated_at = now()
                WHERE id = $1 AND user_id = $2 AND status = 'queued'
                RETURNING id, conversation_id, user_message_id, status
                """,
                run_id, user_id,
            )

    async def complete_assistant_run(
        self,
        user_id: str,
        run_id: str,
        source_mode: str,
        content: Mapping[str, object],
        assistant_client_message_id: str,
    ) -> Mapping[str, object] | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                run = await connection.fetchrow(
                    "SELECT conversation_id, status FROM ai_assistant_runs WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    run_id, user_id,
                )
                if run is None:
                    return None
                if run["status"] == "completed":
                    return await connection.fetchrow(
                        "SELECT id, role, content, client_message_id, created_at FROM ai_messages WHERE id = (SELECT assistant_message_id FROM ai_assistant_runs WHERE id = $1)",
                        run_id,
                    )
                message = await self._append_message(
                    connection,
                    str(uuid.uuid4()),
                    user_id,
                    str(run["conversation_id"]),
                    "assistant",
                    content,
                    assistant_client_message_id,
                )
                if message is None:
                    return None
                await connection.execute(
                    """
                    UPDATE ai_assistant_runs
                    SET status = 'completed', source_mode = $3, assistant_message_id = $4,
                        updated_at = now(), completed_at = now(), error_code = NULL, error_message = NULL
                    WHERE id = $1 AND user_id = $2
                    """,
                    run_id, user_id, source_mode, message["id"],
                )
                return message

    async def fail_assistant_run(self, user_id: str, run_id: str, code: str, message: str) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE ai_assistant_runs
                SET status = 'failed', error_code = $3, error_message = $4, updated_at = now(), completed_at = now()
                WHERE id = $1 AND user_id = $2 AND status IN ('queued', 'running')
                """,
                run_id, user_id, code[:64], message[:500],
            )

    async def _append_message(
        self,
        connection: Connection,
        message_id: str,
        user_id: str,
        conversation_id: str,
        role: str,
        content: Mapping[str, object],
        client_message_id: str | None,
    ) -> Mapping[str, object] | None:
        return await connection.fetchrow(
            """
            WITH owned_conversation AS (
                UPDATE ai_conversations SET updated_at = now()
                WHERE id = $6 AND user_id = $2
                RETURNING id
            )
            INSERT INTO ai_messages (id, conversation_id, user_id, role, content, client_message_id)
            SELECT $1, id, $2, $3, $4::jsonb, $5 FROM owned_conversation
            ON CONFLICT (conversation_id, user_id, client_message_id)
                WHERE client_message_id IS NOT NULL
            DO UPDATE SET client_message_id = ai_messages.client_message_id
            RETURNING id, role, content, client_message_id, created_at
            """,
            message_id,
            user_id,
            role,
            json.dumps(dict(content)),
            client_message_id,
            conversation_id,
        )

    async def list_messages(
        self, user_id: str, conversation_id: str
    ) -> Sequence[Mapping[str, object]]:
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                """
                SELECT m.id, m.role, m.content, m.client_message_id, m.created_at
                FROM ai_messages AS m
                JOIN ai_conversations AS c ON c.id = m.conversation_id
                WHERE m.conversation_id = $1 AND c.user_id = $2
                ORDER BY m.created_at, m.id
                """,
                conversation_id,
                user_id,
            )

    async def list_memories(self, user_id: str) -> Sequence[Mapping[str, object]]:
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                """
                SELECT id, memory_type, memory_key, memory_value, source, confidence, created_at, updated_at
                FROM ai_memories
                WHERE user_id = $1 AND deleted_at IS NULL
                ORDER BY updated_at DESC, id DESC
                """,
                user_id,
            )

    async def get_memory(self, user_id: str, memory_id: str) -> Mapping[str, object] | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(
                """
                SELECT id, memory_type, memory_key, memory_value, source, confidence, created_at, updated_at
                FROM ai_memories
                WHERE id = $1 AND user_id = $2 AND deleted_at IS NULL
                """,
                memory_id,
                user_id,
            )

    async def create_memory(
        self,
        user_id: str,
        memory_type: str,
        memory_key: str,
        memory_value: Mapping[str, object],
        source: str,
        confidence: float,
    ) -> str:
        if memory_type not in {"profile", "episodic"}:
            raise ValueError("memory_type must be profile or episodic")
        if not memory_key.strip() or not source.strip() or not 0 <= confidence <= 1:
            raise ValueError("memory key, source, and confidence are invalid")
        memory_id = str(uuid.uuid4())
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO ai_memories
                        (id, user_id, memory_type, memory_key, memory_value, source, confidence)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                    """,
                    memory_id,
                    user_id,
                    memory_type,
                    memory_key,
                    json.dumps(dict(memory_value)),
                    source,
                    confidence,
                )
                await self._enqueue_projection_task(connection, memory_id, user_id, 1, "upsert")
        return memory_id

    async def upsert_profile_memory(
        self,
        user_id: str,
        memory_key: str,
        memory_value: Mapping[str, object],
        source: str,
        confidence: float,
    ) -> Mapping[str, object]:
        if memory_key != "travel_profile" or not source.strip() or not 0 <= confidence <= 1:
            raise ValueError("memory key, source, and confidence are invalid")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                memory_id = str(uuid.uuid4())
                memory = await connection.fetchrow(
                    """
                    INSERT INTO ai_memories
                        (id, user_id, memory_type, memory_key, memory_value, source, confidence)
                    VALUES ($1, $2, 'profile', $3, $4::jsonb, $5, $6)
                    ON CONFLICT (user_id)
                        WHERE deleted_at IS NULL AND memory_type = 'profile' AND memory_key = 'travel_profile'
                    DO UPDATE SET
                        memory_value = EXCLUDED.memory_value,
                        source = EXCLUDED.source,
                        confidence = EXCLUDED.confidence,
                        updated_at = now(),
                        projection_version = ai_memories.projection_version + 1
                    RETURNING id, memory_type, memory_key, memory_value, source, confidence, created_at,
                        updated_at, projection_version
                    """,
                    memory_id,
                    user_id,
                    memory_key,
                    json.dumps(dict(memory_value)),
                    source,
                    confidence,
                )
                if memory is None:
                    raise RuntimeError("upserted AI memory is unavailable")
                memory_id = str(memory["id"])
                projection_version = int(memory["projection_version"])
                await self._enqueue_projection_task(
                    connection, memory_id, user_id, projection_version, "upsert"
                )
                return {
                    key: value
                    for key, value in memory.items()
                    if key != "projection_version"
                }

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    UPDATE ai_memories
                    SET deleted_at = now(), deleted_by_user_id = $1, updated_at = now(),
                        projection_version = projection_version + 1
                    WHERE id = $2 AND user_id = $1 AND deleted_at IS NULL
                    RETURNING projection_version
                    """,
                    user_id,
                    memory_id,
                )
                if row is None:
                    return False
                await self._enqueue_projection_task(
                    connection, memory_id, user_id, int(row["projection_version"]), "delete"
                )
        return True

    async def update_memory(
        self,
        user_id: str,
        memory_id: str,
        memory_value: Mapping[str, object],
        source: str,
        confidence: float,
    ) -> Mapping[str, object] | None:
        if not source.strip() or not 0 <= confidence <= 1:
            raise ValueError("source and confidence are invalid")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    UPDATE ai_memories
                    SET memory_value = $3::jsonb, source = $4, confidence = $5, updated_at = now(),
                        projection_version = projection_version + 1
                    WHERE id = $2 AND user_id = $1 AND deleted_at IS NULL
                    RETURNING id, memory_type, memory_key, memory_value, source, confidence, created_at,
                        updated_at, projection_version
                    """,
                    user_id,
                    memory_id,
                    json.dumps(dict(memory_value)),
                    source,
                    confidence,
                )
                if row is None:
                    return None
                await self._enqueue_projection_task(
                    connection, memory_id, user_id, int(row["projection_version"]), "upsert"
                )
                return {
                    key: value
                    for key, value in row.items()
                    if key != "projection_version"
                }

    async def _enqueue_projection_task(
        self,
        connection: Connection,
        memory_id: str,
        user_id: str,
        projection_version: int,
        operation: str,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO ai_memory_projection_tasks
                (id, memory_id, user_id, projection_version, operation)
            VALUES ($1, $2, $3, $4, $5)
            """,
            str(uuid.uuid4()),
            memory_id,
            user_id,
            projection_version,
            operation,
        )

    async def load_profile_memory(self, user_id: str) -> Mapping[str, object]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT DISTINCT ON (memory_key) memory_key, memory_value
                FROM ai_memories
                WHERE user_id = $1 AND memory_type = 'profile' AND deleted_at IS NULL
                    AND confidence >= $2
                ORDER BY memory_key, updated_at DESC, id DESC
                """,
                user_id,
                self._profile_confidence_threshold,
            )
        return {str(row["memory_key"]): row["memory_value"] for row in rows}

    async def filter_active_projected_memory_documents(
        self, user_id: str, document_versions: Mapping[str, str]
    ) -> set[str]:
        """Return only retrieved documents still owned and current for this user."""
        if not document_versions:
            return set()
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT memory.id::text AS id
                FROM ai_memories AS memory
                JOIN unnest($2::text[], $3::text[]) AS requested(id, source_version)
                    ON requested.id = memory.id::text
                    AND requested.source_version = memory.projection_version::text
                WHERE memory.user_id = $1 AND memory.memory_type = 'profile'
                    AND memory.deleted_at IS NULL
                """,
                user_id,
                list(document_versions),
                list(document_versions.values()),
            )
        return {str(row["id"]) for row in rows}

    async def save_preview(
        self,
        request: GenerationRequest,
        draft: VerifiedItineraryDraft,
        citations: tuple[Citation, ...],
        audit: tuple[NodeAudit, ...],
    ) -> SavedPreview:
        from app.modules.ai_workflows.contracts import SavedPreview

        preview_id = str(uuid.uuid4())
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    INSERT INTO ai_generation_previews
                        (id, user_id, generation_job_id, draft, target_itinerary_id, base_version)
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                    ON CONFLICT (generation_job_id) DO NOTHING
                    RETURNING id
                    """,
                    preview_id,
                    request.user_id,
                    request.generation_job_id,
                    json.dumps(_draft_json(draft)),
                    request.target_itinerary_id,
                    request.base_version,
                )
                if row is None:
                    row = await connection.fetchrow(
                        "SELECT id FROM ai_generation_previews WHERE generation_job_id = $1 AND user_id = $2",
                        request.generation_job_id,
                        request.user_id,
                    )
                    if row is None:
                        raise PermissionError("generation preview belongs to another user")
                    return SavedPreview(preview_id=str(row["id"]))
                for position, citation in enumerate(citations):
                    source_type, source_id, content = _preview_citation_fields(citation)
                    await connection.execute(
                        """
                        INSERT INTO ai_preview_citations
                        (id, preview_id, position, document_id, chunk_id, source_type, source_id,
                         city_code, source_updated_at, content)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        """,
                        str(uuid.uuid4()), preview_id, position, citation.document_id,
                        citation.chunk_id, source_type, source_id,
                        citation.city_code, citation.source_updated_at, content,
                    )
                for position, node_audit in enumerate(audit):
                    await connection.execute(
                        """
                        INSERT INTO ai_preview_audits
                            (id, preview_id, position, node, status, agent_version, duration_ms,
                             redacted_summary, tool_summary, degradations, review_codes)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb)
                        """,
                        str(uuid.uuid4()),
                        preview_id,
                        position,
                        node_audit.node,
                        node_audit.status,
                        node_audit.agent_version,
                        node_audit.duration_ms,
                        node_audit.redacted_summary,
                        json.dumps(dict(node_audit.tool_summary))
                        if node_audit.tool_summary is not None
                        else None,
                        json.dumps(node_audit.degradations),
                        json.dumps(node_audit.review_codes),
                    )
        return SavedPreview(preview_id=preview_id)

    async def get_preview(self, user_id: str, preview_id: str) -> Mapping[str, object] | None:
        async with self._pool.acquire() as connection:
            preview = await connection.fetchrow(
                """
                    SELECT id, generation_job_id, draft, prompt_version, model_version, created_at,
                           target_itinerary_id, base_version
                FROM ai_generation_previews
                WHERE id = $1 AND user_id = $2 AND state = 'preview'
                """,
                preview_id,
                user_id,
            )
            if preview is None:
                return None
            citations = await connection.fetch(
                """
                SELECT document_id, chunk_id, source_type, source_id, city_code, source_updated_at, content
                FROM ai_preview_citations WHERE preview_id = $1 ORDER BY position
                """,
                preview_id,
            )
        draft = preview["draft"]
        if isinstance(draft, str):
            draft = json.loads(draft)
        if not isinstance(draft, Mapping):
            raise ValueError("Stored AI preview draft is not a JSON object")
        return {
            "id": str(preview["id"]),
            "generation_job_id": str(preview["generation_job_id"]),
            "draft": dict(draft),
            "prompt_version": preview["prompt_version"],
            "model_version": preview["model_version"],
            "created_at": preview["created_at"],
            "target_itinerary_id": preview.get("target_itinerary_id"),
            "base_version": preview.get("base_version"),
            "citations": [dict(citation) for citation in citations],
        }


def _draft_json(draft: VerifiedItineraryDraft) -> dict[str, object]:
    return {
        "title": draft.title,
        "days": [
            {
                "date": day.day_date.isoformat(),
                "activities": [
                    {
                        "poi_id": activity.poi.poi_id,
                        "poi_name": activity.poi.name,
                        "longitude": activity.poi.longitude,
                        "latitude": activity.poi.latitude,
                        "title": activity.activity.title,
                        "estimated_cost": activity.activity.estimated_cost,
                        **({"event_id": activity.activity.event_id} if activity.activity.event_id else {}),
                    }
                    for activity in day.activities
                ],
            }
            for day in draft.days
        ],
    }


def _preview_citation_fields(citation: Citation) -> tuple[str, str, str]:
    """Expose only the two public source labels and bounded citation metadata."""
    if citation.source_type != "live_web":
        return "reviewed_knowledge", citation.source_id, citation.content
    from urllib.parse import urlparse

    parsed = urlparse(citation.source_id)
    source_id = parsed.hostname or citation.source_id
    return "live_web", source_id, citation.content[:2000]
