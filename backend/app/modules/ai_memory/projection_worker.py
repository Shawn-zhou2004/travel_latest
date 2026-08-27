from __future__ import annotations

import uuid
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

from app.core.settings import Settings
from app.modules.ai_memory.postgres import AsyncpgPoolFactory, Pool
from app.modules.ai_memory.projection import ExplicitMemorySource, MemoryProjectionService
from app.modules.ai_rag.ingestion import KnowledgeIngestionService
from app.modules.ai_rag.protocols import ElasticsearchBm25Store, MilvusDenseStore
from app.modules.ai_rag.types import KnowledgeDomain

if TYPE_CHECKING:
    from app.modules.ai_workflows.runtime import DomainRetrievalRuntime


@dataclass(frozen=True)
class ProjectionTask:
    id: str
    memory_id: str
    user_id: str
    projection_version: int
    lease_token: str
    attempt_count: int


class Connection(Protocol):
    async def execute(self, query: str, *args: object) -> str: ...

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None: ...

    def transaction(self) -> Any: ...


class MemoryProjection(Protocol):
    async def project(self, memory: ExplicitMemorySource) -> object: ...

    async def delete(self, memory: ExplicitMemorySource) -> None: ...


class PrivateMemoryDeletion:
    """Deletes a private document from both projections before replacement."""

    def __init__(self, milvus: MilvusDenseStore, elasticsearch: ElasticsearchBm25Store) -> None:
        self._milvus = milvus
        self._elasticsearch = elasticsearch

    async def delete_document(self, document_id: str) -> None:
        await self._milvus.delete_document(document_id)
        await self._elasticsearch.delete_document(document_id)


class MemoryProjectionWorker:
    """Durably drains PostgreSQL memory projection requests in source-version order."""

    def __init__(
        self,
        pool: Pool,
        projection: MemoryProjection,
        *,
        lease_seconds: int = 300,
        maximum_retry_delay_seconds: int = 300,
    ) -> None:
        if lease_seconds < 1 or maximum_retry_delay_seconds < 1:
            raise ValueError("projection lease and retry delays must be positive")
        self._pool = pool
        self._projection = projection
        self._lease_seconds = lease_seconds
        self._maximum_retry_delay_seconds = maximum_retry_delay_seconds

    async def drain(self, *, limit: int = 20) -> int:
        if limit < 1:
            raise ValueError("projection drain limit must be positive")
        completed = 0
        for _ in range(limit):
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    task = await self._claim_task(connection)
            if task is None:
                return completed
            try:
                async with self._pool.acquire() as connection:
                    async with connection.transaction():
                        source = await connection.fetchrow(
                            """
                            SELECT id, user_id, memory_key, memory_value, updated_at, deleted_at,
                                projection_version
                            FROM ai_memories
                            WHERE id = $1 AND user_id = $2
                            FOR UPDATE
                            """,
                            task.memory_id,
                            task.user_id,
                        )
                        if source is None or int(source["projection_version"]) < task.projection_version:
                            raise RuntimeError(
                                "projection source is not available at the requested version"
                            )
                        if int(source["projection_version"]) > task.projection_version:
                            await self._complete(connection, task)
                            completed += 1
                            continue

                        memory_value = _memory_value(source["memory_value"])
                        memory = ExplicitMemorySource(
                            memory_id=str(source["id"]),
                            user_id=str(source["user_id"]),
                            memory_key=str(source["memory_key"]),
                            memory_value=memory_value,
                            updated_at=cast(datetime, source["updated_at"]),
                            projection_version=int(source["projection_version"]),
                        )
                        if source["deleted_at"] is None:
                            # Delete first so an updated document cannot retain stale chunks.
                            await self._projection.delete(memory)
                            await self._projection.project(memory)
                        else:
                            await self._projection.delete(memory)
                        await self._complete(connection, task)
                        completed += 1
            except Exception as exc:
                await self._retry(task, exc)
                return completed
        return completed

    async def _claim_task(self, connection: Connection) -> ProjectionTask | None:
        lease_token = str(uuid.uuid4())
        row = await connection.fetchrow(
            """
            WITH recovered_leases AS (
                UPDATE ai_memory_projection_tasks
                SET status = 'requested', lease_token = NULL, lease_expires_at = NULL,
                    available_at = now()
                WHERE status = 'leased' AND lease_expires_at <= now()
            ), candidate AS (
                SELECT id
                FROM ai_memory_projection_tasks
                WHERE status = 'requested' AND available_at <= now()
                ORDER BY available_at, created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE ai_memory_projection_tasks AS task
            SET status = 'leased', lease_token = $1,
                lease_expires_at = now() + $2 * interval '1 second',
                attempt_count = task.attempt_count + 1
            FROM candidate
            WHERE task.id = candidate.id
                AND task.status = 'requested' AND task.available_at <= now()
            RETURNING task.id, task.memory_id, task.user_id, task.projection_version,
                task.lease_token, task.attempt_count
            """,
            lease_token,
            self._lease_seconds,
        )
        if row is None:
            return None
        return ProjectionTask(
            id=str(row["id"]),
            memory_id=str(row["memory_id"]),
            user_id=str(row["user_id"]),
            projection_version=int(row["projection_version"]),
            lease_token=str(row["lease_token"]),
            attempt_count=int(row["attempt_count"]),
        )

    async def _complete(self, connection: Connection, task: ProjectionTask) -> None:
        await connection.execute(
            """
            UPDATE ai_memory_projection_tasks
            SET status = 'completed', completed_at = now(), lease_token = NULL,
                lease_expires_at = NULL, last_error = NULL
            WHERE id = $1 AND status = 'leased' AND lease_token = $2
                AND projection_version = $3
            """,
            task.id,
            task.lease_token,
            task.projection_version,
        )

    async def _retry(self, task: ProjectionTask, error: Exception) -> None:
        delay_seconds = min(
            2 ** (task.attempt_count - 1), self._maximum_retry_delay_seconds
        )
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    UPDATE ai_memory_projection_tasks
                    SET status = 'requested', lease_token = NULL, lease_expires_at = NULL,
                        available_at = now() + $3 * interval '1 second', last_error = $4
                    WHERE id = $1 AND status = 'leased' AND lease_token = $2
                    """,
                    task.id,
                    task.lease_token,
                    delay_seconds,
                    str(error),
                )


@asynccontextmanager
async def open_memory_projection_worker(settings: Settings) -> AsyncIterator[MemoryProjectionWorker]:
    pool_factory = AsyncpgPoolFactory(settings.ai_postgres_dsn or "")
    runtime: DomainRetrievalRuntime | None = None
    try:
        pool = await pool_factory.open()
        from app.modules.ai_workflows.runtime import open_domain_retrieval_runtime

        runtime = await open_domain_retrieval_runtime(settings)
        milvus, elasticsearch = runtime.catalog.stores[KnowledgeDomain.USER_MEMORY]
        projection = MemoryProjectionService(
            KnowledgeIngestionService(runtime.embeddings, milvus, elasticsearch),
            PrivateMemoryDeletion(milvus, elasticsearch),
        )
        yield MemoryProjectionWorker(pool, projection)
    finally:
        if runtime is not None:
            await runtime.close()
        await pool_factory.close()


def _memory_value(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("private memory value must be a JSON object")
    return cast(Mapping[str, object], value)
