from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.events.consumer import EventRoute, RabbitMQEventConsumer, consume_once
from app.models.base import Base
from app.models.outbox import OutboxEvent


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
async def test_consumer_deduplicates_same_event_per_consumer(session: AsyncSession) -> None:
    event = OutboxEvent(
        event_type="itinerary.published",
        aggregate_type="itinerary",
        aggregate_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        payload_json={"status": "published"},
    )
    session.add(event)
    await session.commit()
    envelope = {"event_id": event.event_id, "event_type": event.event_type, "payload": {}}

    assert await consume_once(session, "search.trip.index", envelope) is True
    assert await consume_once(session, "search.trip.index", envelope) is False


@pytest.mark.anyio
async def test_consumer_handler_shares_idempotency_transaction(session: AsyncSession) -> None:
    event = OutboxEvent(
        event_type="itinerary.published",
        aggregate_type="itinerary",
        aggregate_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        payload_json={"status": "published"},
    )
    session.add(event)
    await session.commit()
    seen: list[str] = []

    async def handler(_session: AsyncSession, envelope: dict[str, object]) -> None:
        seen.append(str(envelope["event_id"]))

    envelope = {"event_id": event.event_id, "event_type": event.event_type, "payload": {}}
    assert await consume_once(session, "notifications", envelope, handler) is True
    assert seen == [event.event_id]


@pytest.mark.anyio
async def test_consumer_handler_failure_rolls_back_idempotency_record(
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

    async def failing_handler(_session: AsyncSession, _envelope: dict[str, object]) -> None:
        raise RuntimeError("temporary projection failure")

    envelope = {"event_id": event.event_id, "event_type": event.event_type, "payload": {}}
    with pytest.raises(RuntimeError, match="temporary projection failure"):
        await consume_once(session, "search.itinerary.index", envelope, failing_handler)

    assert await consume_once(session, "search.itinerary.index", envelope) is True


@pytest.mark.anyio
async def test_rabbit_consumer_dispatches_registered_route_and_acks_message(
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
    seen: list[str] = []

    async def handler(_session: AsyncSession, envelope: dict[str, object]) -> None:
        seen.append(str(envelope["event_id"]))

    class FakeMessage:
        body = (
            '{"event_id": "' + event.event_id + '", '
            '"event_type": "itinerary.published", "payload": {}}'
        ).encode()
        headers: dict[str, object] = {}
        acked = False
        rejected = False

        async def ack(self) -> None:
            self.acked = True

        async def reject(self, *, requeue: bool) -> None:
            del requeue
            self.rejected = True

    class FakeBroker:
        worker_queue = object()

        async def publish_dead_letter(
            self, envelope: dict[str, object], *, reason: str, attempts: int
        ) -> None:
            del envelope, reason, attempts

    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    consumer = RabbitMQEventConsumer(
        FakeBroker(),
        factory,
        {"itinerary.published": (EventRoute("search.itinerary.index", handler),)},
    )
    message = FakeMessage()

    await consumer._handle_message(message)

    assert message.acked is True
    assert message.rejected is False
    assert seen == [event.event_id]


@pytest.mark.anyio
async def test_rabbit_consumer_dead_letters_malformed_message() -> None:
    class FakeMessage:
        body = b"not-json"
        headers: dict[str, object] = {}
        acked = False
        rejected = False

        async def ack(self) -> None:
            self.acked = True

        async def reject(self, *, requeue: bool) -> None:
            del requeue
            self.rejected = True

    class FakeBroker:
        worker_queue = object()
        dead_letters: list[tuple[dict[str, object], str, int]] = []

        async def publish_dead_letter(
            self, envelope: dict[str, object], *, reason: str, attempts: int
        ) -> None:
            self.dead_letters.append((envelope, reason, attempts))

    broker = FakeBroker()
    consumer = RabbitMQEventConsumer(broker, object(), {})
    message = FakeMessage()

    await consumer._handle_message(message)

    assert message.acked is True
    assert message.rejected is False
    assert broker.dead_letters[0][0] == {"event_type": "worker.malformed_event"}
