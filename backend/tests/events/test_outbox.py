from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.events.publisher import publish_pending_events
from app.models.base import Base
from app.models.outbox import OutboxEvent


class FakeBroker:
    def __init__(self, *, confirmed: bool = True) -> None:
        self.confirmed = confirmed
        self.confirmed_event_ids: list[str] = []

    async def publish(self, envelope: dict[str, object]) -> bool:
        if self.confirmed:
            self.confirmed_event_ids.append(str(envelope["event_id"]))
        return self.confirmed


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as database_session:
        yield database_session
    await engine.dispose()


@pytest.mark.anyio
async def test_publisher_marks_event_published_only_after_confirm(session: AsyncSession) -> None:
    event = OutboxEvent(
        event_type="itinerary.published",
        aggregate_type="itinerary",
        aggregate_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        payload_json={"itinerary_id": "itinerary-1", "status": "published"},
    )
    session.add(event)
    await session.commit()
    broker = FakeBroker()

    published = await publish_pending_events(session, broker)

    assert published == [event.event_id]
    assert broker.confirmed_event_ids == [event.event_id]
    assert event.published_at is not None


@pytest.mark.anyio
async def test_publisher_keeps_event_pending_when_broker_does_not_confirm(
    session: AsyncSession,
) -> None:
    event = OutboxEvent(
        event_type="itinerary.published",
        aggregate_type="itinerary",
        aggregate_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        payload_json={"status": "published"},
    )
    session.add(event)
    await session.commit()

    published = await publish_pending_events(session, FakeBroker(confirmed=False))

    assert published == []
    assert event.published_at is None
    assert event.retry_count == 1


def test_pending_outbox_scan_has_a_matching_index_without_row_locks() -> None:
    index = next(index for index in OutboxEvent.__table__.indexes if index.name == "ix_outbox_events_pending")
    assert [column.name for column in index.columns] == ["published_at", "created_at", "event_id"]

    statement = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at, OutboxEvent.event_id)
        .limit(100)
    )
    assert "FOR UPDATE" not in str(statement)
