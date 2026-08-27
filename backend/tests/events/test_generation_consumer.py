from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.events.consumer import EventRoute, RabbitMQEventConsumer
from app.models.base import Base
from app.models.outbox import ProcessedEvent
from app.modules.ai_workflows.models import GenerationJob
from app.workers.domain_handlers import _finalize_generation_failure


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _generation_job(factory: async_sessionmaker[AsyncSession]) -> GenerationJob:
    async with factory() as session:
        job = GenerationJob(
            user_id=str(uuid.uuid4()),
            target_itinerary_id=None,
            idempotency_key="generation-retry",
            city_code="330100",
            prompt="Plan a day in Hangzhou",
            start_date=date(2026, 8, 7),
            end_date=date(2026, 8, 7),
            request_json={},
        )
        session.add(job)
        await session.commit()
        return job


class _Message:
    def __init__(self, envelope: dict[str, object], attempts: int = 0) -> None:
        self.body = json.dumps(envelope).encode()
        self.headers: dict[str, object] = {"attempts": attempts}
        self.acked = False
        self.rejected = False

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, *, requeue: bool) -> None:
        assert requeue is False
        self.rejected = True


class _Broker:
    worker_queue = object()

    def __init__(self) -> None:
        self.dead_letters: list[tuple[dict[str, object], str, int]] = []

    async def publish_dead_letter(
        self, envelope: dict[str, object], *, reason: str, attempts: int
    ) -> None:
        self.dead_letters.append((envelope, reason, attempts))


@pytest.mark.anyio
async def test_generation_retry_rejects_without_recording_processed_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job = await _generation_job(session_factory)

    async def transient_failure(session: AsyncSession, event: dict[str, Any]) -> None:
        claimed = await session.get(GenerationJob, job.id)
        assert claimed is not None
        claimed.attempt_count += 1
        claimed.trace_id = str(event["trace_id"])
        await session.commit()
        claimed.status = "queued"
        await session.commit()
        raise RuntimeError("provider detail must not persist")

    broker = _Broker()
    consumer = RabbitMQEventConsumer(
        broker,
        session_factory,
        {
            "ai.generation_requested": (
                EventRoute("ai.generation", transient_failure, defer_idempotency=True),
            )
        },
    )
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "ai.generation_requested",
        "trace_id": str(uuid.uuid4()),
        "payload": {"generation_job_id": job.id},
    }
    message = _Message(event)

    await consumer._handle_message(message)

    assert message.rejected is True
    assert message.acked is False
    async with session_factory() as session:
        processed = await session.scalar(
            select(ProcessedEvent).where(
                ProcessedEvent.consumer_name == "ai.generation",
                ProcessedEvent.event_id == event["event_id"],
            )
        )
        assert processed is None
        retried_job = await session.get(GenerationJob, job.id)
        assert retried_job is not None
        assert retried_job.status == "queued"
        assert retried_job.attempt_count == 1
        assert retried_job.trace_id == event["trace_id"]


@pytest.mark.anyio
async def test_generation_final_exhaustion_finalizes_job_then_dead_letters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job = await _generation_job(session_factory)

    async def transient_failure(session: AsyncSession, _event: dict[str, Any]) -> None:
        claimed = await session.get(GenerationJob, job.id)
        assert claimed is not None
        claimed.status = "queued"
        raise RuntimeError("provider connection reset")

    broker = _Broker()
    consumer = RabbitMQEventConsumer(
        broker,
        session_factory,
        {
            "ai.generation_requested": (
                EventRoute(
                    "ai.generation",
                    transient_failure,
                    defer_idempotency=True,
                    terminal_failure_handler=_finalize_generation_failure,
                ),
            )
        },
        max_attempts=3,
    )
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "ai.generation_requested",
        "payload": {"generation_job_id": job.id},
    }
    message = _Message(event, attempts=2)

    await consumer._handle_message(message)

    assert message.acked is True
    assert message.rejected is False
    assert broker.dead_letters[0][2] == 3
    assert "provider connection reset" in broker.dead_letters[0][1]
    async with session_factory() as session:
        exhausted_job = await session.get(GenerationJob, job.id)
        assert exhausted_job is not None
        assert exhausted_job.status == "failed"
        assert exhausted_job.outcome == "unavailable"
        assert exhausted_job.error_code == "AI_DEPENDENCY_UNAVAILABLE"
        assert exhausted_job.message == "AI planning dependencies are temporarily unavailable."
