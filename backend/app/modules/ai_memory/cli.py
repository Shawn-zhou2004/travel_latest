from __future__ import annotations

import asyncio
import argparse
import selectors
import sys
from datetime import date

from app.core.settings import Settings
from app.core.database import SessionLocal, engine
from app.modules.ai_memory.postgres import (
    AIMemoryRepository,
    AsyncpgPoolFactory,
    open_langgraph_checkpointer,
)
from app.modules.ai_memory.projection_worker import open_memory_projection_worker
from app.modules.ai_workflows.runtime import open_ai_runtime
from app.modules.ai_workflows.contracts import Citation, GenerationRequest
from app.modules.community.models import Post
from app.modules.ai_rag.types import KnowledgeSourceType, ReviewedKnowledgeDocument
from sqlalchemy import select


async def initialize() -> None:
    settings = Settings()
    if not settings.ai_enabled:
        raise ValueError("AI_ENABLED must be true before initializing AI PostgreSQL storage")
    factory = AsyncpgPoolFactory(settings.ai_postgres_dsn or "")
    try:
        pool = await factory.open()
        await AIMemoryRepository(pool).setup_schema()
        async with open_langgraph_checkpointer(settings.ai_postgres_dsn or ""):
            pass
    finally:
        await factory.close()


async def check_runtime() -> None:
    settings = Settings()
    runtime = await open_ai_runtime(settings)
    await runtime.close()


async def check_providers() -> None:
    settings = Settings()
    runtime = await open_ai_runtime(settings)
    try:
        vector = await runtime.embeddings.embed_query("AI travel platform connectivity check")
        if len(vector) != settings.embedding_dimensions:
            raise RuntimeError("Embedding provider returned an unexpected vector dimension")
        await runtime.generator.generate(
            GenerationRequest(
                generation_job_id="00000000-0000-4000-8000-000000000001",
                user_id="00000000-0000-4000-8000-000000000002",
                prompt="Return a one-day source-backed itinerary.",
                city_code="330100",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 1),
            ),
            {},
            (
                Citation(
                    document_id="health-check",
                    chunk_id="health-check:0",
                    source_type="rule",
                    source_id="health-check",
                    city_code="330100",
                    source_updated_at="2026-08-05T00:00:00Z",
                    content="Use only verified POIs supplied by travel knowledge.",
                ),
            ),
        )
    finally:
        await runtime.close()
        await engine.dispose()


async def drain_projection_tasks() -> int:
    settings = Settings()
    if not settings.ai_enabled:
        raise ValueError("AI_ENABLED must be true before draining private memory projections")
    async with open_memory_projection_worker(settings) as worker:
        return await worker.drain()


async def projection_task_status() -> list[tuple[str, int, int, str | None, int]]:
    settings = Settings()
    factory = AsyncpgPoolFactory(settings.ai_postgres_dsn or "")
    try:
        pool = await factory.open()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT status, COUNT(*) AS task_count,
                    COUNT(last_error) AS errored_count,
                    MIN(last_error) AS sample_error,
                    GREATEST(0, FLOOR(EXTRACT(EPOCH FROM MIN(available_at) - now())))::int
                        AS next_available_in_seconds
                FROM ai_memory_projection_tasks
                GROUP BY status
                ORDER BY status
                """
            )
        return [
            (
                str(row["status"]),
                int(row["task_count"]),
                int(row["errored_count"]),
                _projection_error_kind(row["sample_error"]),
                int(row["next_available_in_seconds"]),
            )
            for row in rows
        ]
    finally:
        await factory.close()


def _projection_error_kind(error: object) -> str | None:
    if not isinstance(error, str) or not error:
        return None
    return error.split(":", 1)[0].strip()[:80] or "unknown"


async def backfill_published_community(limit: int) -> int:
    settings = Settings()
    runtime = await open_ai_runtime(settings)
    try:
        async with SessionLocal() as session:
            posts = list(
                (
                    await session.scalars(
                        select(Post)
                        .where(Post.status == "published", Post.city_code.is_not(None))
                        .order_by(Post.updated_at.desc())
                        .limit(limit)
                    )
                ).all()
            )
        for post in posts:
            await runtime.ingestion_service().ingest(
                ReviewedKnowledgeDocument(
                    document_id=post.id,
                    source_type=KnowledgeSourceType.COMMUNITY,
                    source_id=post.id,
                    text=f"{post.title}\n\n{post.body_text}",
                    city_code=post.city_code,
                    poi_id=None,
                    language="zh-CN",
                    visibility="public",
                    status="reviewed",
                    source_updated_at=post.updated_at,
                )
            )
        return len(posts)
    finally:
        await runtime.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize or verify AI PostgreSQL and cloud runtime.")
    parser.add_argument("--check-runtime", action="store_true")
    parser.add_argument("--check-providers", action="store_true")
    parser.add_argument("--backfill-published-community", type=int, metavar="LIMIT")
    parser.add_argument("--drain-projection-tasks", action="store_true")
    parser.add_argument("--projection-task-status", action="store_true")
    args = parser.parse_args()
    if sum((args.check_runtime, args.check_providers, args.backfill_published_community is not None, args.drain_projection_tasks, args.projection_task_status)) > 1:
        parser.error("choose only one action")
    try:
        operation = (
            (lambda: backfill_published_community(args.backfill_published_community))
            if args.backfill_published_community is not None
            else projection_task_status if args.projection_task_status else drain_projection_tasks if args.drain_projection_tasks else check_providers if args.check_providers else check_runtime if args.check_runtime else initialize
        )
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) as runner:
                result = runner.run(operation())
        else:
            result = asyncio.run(operation())
    except Exception as error:
        print(f"AI PostgreSQL initialization failed: {error}")
        return 2
    if args.backfill_published_community is not None:
        print(f"Indexed {result} published community records into AI knowledge.")
    elif args.drain_projection_tasks:
        print(f"Completed {result} private memory projection tasks.")
    elif args.projection_task_status:
        for task_status, task_count, errored_count, error_kind, available_in_seconds in result:
            suffix = f" error_kind={error_kind}" if error_kind else ""
            print(
                f"status={task_status} tasks={task_count} errored={errored_count}"
                f" next_available_in_seconds={available_in_seconds}{suffix}"
            )
    elif args.check_providers:
        print("Embedding and DashScope providers are reachable.")
    else:
        print("AI cloud runtime is reachable." if args.check_runtime else "AI PostgreSQL and LangGraph checkpoint schemas are initialized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
