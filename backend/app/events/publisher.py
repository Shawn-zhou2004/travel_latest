from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utc_now
from app.models.outbox import OutboxEvent


DOMAIN_EVENTS_EXCHANGE = "domain.events"
RETRY_EVENTS_EXCHANGE = "domain.events.retry"
DLQ_EVENTS_EXCHANGE = "domain.events.dlq"
WORKER_EVENTS_QUEUE = "worker.events"
RETRY_EVENTS_QUEUE = "worker.events.retry"
DLQ_EVENTS_QUEUE = "worker.events.dlq"
RETRY_DELAY_MS = 5_000


class EventBroker(Protocol):
    async def publish(self, envelope: Mapping[str, Any]) -> bool:
        """Publish an event and return whether the broker confirmed it."""


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return _format_timestamp(value)
    return value


def _format_timestamp(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    occurred_at: str
    trace_id: str
    payload: Mapping[str, object]

    @classmethod
    def from_outbox(cls, event: OutboxEvent) -> "EventEnvelope":
        payload = _json_value(event.payload_json)
        if not isinstance(payload, Mapping):
            raise TypeError("Outbox payload must be a JSON object")
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            occurred_at=_format_timestamp(event.occurred_at),
            trace_id=event.trace_id,
            payload=payload,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "occurred_at": self.occurred_at,
            "trace_id": self.trace_id,
            "payload": dict(self.payload),
        }


async def publish_pending_events(
    session: AsyncSession,
    broker: EventBroker,
    *,
    batch_size: int = 100,
) -> list[str]:
    """Publish pending rows and mark them only after broker confirmation.

    The stable event ID makes a publish-before-database-commit crash safe for
    consumers: a repeated delivery is treated as the same event.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    statement = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at, OutboxEvent.event_id)
        .limit(batch_size)
    )
    events = list((await session.scalars(statement)).all())
    published_ids: list[str] = []

    for event in events:
        envelope = EventEnvelope.from_outbox(event).as_dict()
        try:
            confirmed = await broker.publish(envelope)
        except Exception:
            event.retry_count += 1
            event.updated_at = utc_now()
            continue

        if confirmed is False:
            event.retry_count += 1
            event.updated_at = utc_now()
            continue

        event.published_at = utc_now()
        event.updated_at = utc_now()
        published_ids.append(event.event_id)

    if events:
        await session.commit()
    return published_ids


class RabbitMQEventBroker:
    """RabbitMQ publisher-confirm client and shared event topology."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.connection: Any = None
        self.channel: Any = None
        self.exchange: Any = None
        self.retry_exchange: Any = None
        self.dlq_exchange: Any = None
        self.worker_queue: Any = None

    async def connect(self) -> None:
        import aio_pika
        from aio_pika import ExchangeType
        self.connection = await aio_pika.connect_robust(self.url)
        self.channel = await self.connection.channel(publisher_confirms=True)
        self.exchange = await self.channel.declare_exchange(
            DOMAIN_EVENTS_EXCHANGE, ExchangeType.TOPIC, durable=True
        )
        self.retry_exchange = await self.channel.declare_exchange(
            RETRY_EVENTS_EXCHANGE, ExchangeType.TOPIC, durable=True
        )
        self.dlq_exchange = await self.channel.declare_exchange(
            DLQ_EVENTS_EXCHANGE, ExchangeType.TOPIC, durable=True
        )
        self.worker_queue = await self.channel.declare_queue(
            WORKER_EVENTS_QUEUE,
            durable=True,
            arguments={"x-dead-letter-exchange": RETRY_EVENTS_EXCHANGE},
        )
        retry_queue = await self.channel.declare_queue(
            RETRY_EVENTS_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": RETRY_DELAY_MS,
                "x-dead-letter-exchange": DOMAIN_EVENTS_EXCHANGE,
            },
        )
        dlq_queue = await self.channel.declare_queue(DLQ_EVENTS_QUEUE, durable=True)
        await self.worker_queue.bind(self.exchange, routing_key="#")
        await retry_queue.bind(self.retry_exchange, routing_key="#")
        await dlq_queue.bind(self.dlq_exchange, routing_key="#")

    async def publish(self, envelope: Mapping[str, Any]) -> bool:
        if self.exchange is None:
            raise RuntimeError("RabbitMQ broker is not connected")
        import aio_pika

        message = aio_pika.Message(
            body=json.dumps(envelope, separators=(",", ":"), ensure_ascii=True).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(envelope["event_id"]),
            headers={"event_type": str(envelope["event_type"])},
        )
        confirmed = await self.exchange.publish(message, routing_key=str(envelope["event_type"]))
        return confirmed is not False

    async def publish_dead_letter(
        self, envelope: Mapping[str, Any], *, reason: str, attempts: int
    ) -> None:
        if self.dlq_exchange is None:
            raise RuntimeError("RabbitMQ broker is not connected")
        import aio_pika

        message = aio_pika.Message(
            body=json.dumps(envelope, separators=(",", ":"), ensure_ascii=True).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(envelope.get("event_id", "unknown")),
            headers={"failure_reason": reason[:500], "attempts": attempts},
        )
        await self.dlq_exchange.publish(
            message, routing_key=str(envelope.get("event_type", "worker.malformed_event"))
        )

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
