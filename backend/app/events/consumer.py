from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events.publisher import RabbitMQEventBroker
from app.models.base import new_uuid
from app.models.outbox import ProcessedEvent


EventHandler = Callable[[AsyncSession, Mapping[str, Any]], Awaitable[None]]
TerminalFailureHandler = Callable[[AsyncSession, Mapping[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class EventRoute:
    consumer_name: str
    handler: EventHandler
    defer_idempotency: bool = False
    terminal_failure_handler: TerminalFailureHandler | None = None


class EventRouteRegistry:
    def __init__(self) -> None:
        self._routes: dict[str, list[EventRoute]] = {}

    def register(
        self,
        event_type: str,
        consumer_name: str,
        handler: EventHandler,
        *,
        defer_idempotency: bool = False,
        terminal_failure_handler: TerminalFailureHandler | None = None,
    ) -> None:
        if not event_type or not consumer_name:
            raise ValueError("event_type and consumer_name are required")
        self._routes.setdefault(event_type, []).append(
            EventRoute(consumer_name, handler, defer_idempotency, terminal_failure_handler)
        )

    def snapshot(self) -> dict[str, tuple[EventRoute, ...]]:
        return {event_type: tuple(routes) for event_type, routes in self._routes.items()}


registered_routes = EventRouteRegistry()


class UnhandledEventError(RuntimeError):
    pass


async def consume_once(
    session: AsyncSession,
    consumer_name: str,
    event: Mapping[str, Any],
    handler: EventHandler | None = None,
    *,
    defer_idempotency: bool = False,
) -> bool:
    """Run one event handler exactly once for a consumer name.

    The idempotency insert and optional projection handler share the same
    session transaction. A duplicate event rolls back only this delivery and
    returns False; handler failures are re-raised for broker retry handling.
    """

    event_id = str(event.get("event_id", ""))
    if not event_id:
        raise ValueError("event.event_id is required")
    if not consumer_name:
        raise ValueError("consumer_name is required")

    existing = await session.scalar(
        select(ProcessedEvent.id).where(
            ProcessedEvent.consumer_name == consumer_name,
            ProcessedEvent.event_id == event_id,
        )
    )
    if existing is not None:
        await session.rollback()
        return False

    try:
        if not defer_idempotency:
            await session.execute(
                insert(ProcessedEvent).values(
                    id=new_uuid(),
                    consumer_name=consumer_name,
                    event_id=event_id,
                )
            )
        if handler is not None:
            await handler(session, event)
        if defer_idempotency:
            await session.execute(
                insert(ProcessedEvent).values(
                    id=new_uuid(),
                    consumer_name=consumer_name,
                    event_id=event_id,
                )
            )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(ProcessedEvent.id).where(
                ProcessedEvent.consumer_name == consumer_name,
                ProcessedEvent.event_id == event_id,
            )
        )
        await session.rollback()
        if existing is not None:
            return False
        raise
    except Exception:
        await session.rollback()
        raise
    return True


def _delivery_attempts(headers: Mapping[str, Any] | None) -> int:
    if not headers:
        return 0
    deaths = headers.get("x-death", [])
    if isinstance(deaths, list) and deaths:
        return sum(int(item.get("count", 0)) for item in deaths if isinstance(item, Mapping))
    return int(headers.get("attempts", 0) or 0)


class RabbitMQEventConsumer:
    def __init__(
        self,
        broker: RabbitMQEventBroker,
        session_factory: async_sessionmaker[AsyncSession],
        routes: Mapping[str, Sequence[EventRoute]],
        *,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.broker = broker
        self.session_factory = session_factory
        self.routes = routes
        self.max_attempts = max_attempts

    async def run(self) -> None:
        if self.broker.worker_queue is None:
            raise RuntimeError("RabbitMQ broker is not connected")
        await self.broker.worker_queue.consume(self._handle_message)
        import asyncio

        await asyncio.Future()

    async def _handle_message(self, message: Any) -> None:
        envelope: dict[str, Any] = {}
        active_route: EventRoute | None = None
        attempts = _delivery_attempts(getattr(message, "headers", None)) + 1
        try:
            decoded = json.loads(message.body.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("event message must be a JSON object")
            envelope = decoded
            event_type = str(envelope.get("event_type", ""))
            routes = self.routes.get(event_type, ())
            if not routes:
                raise UnhandledEventError(f"No registered handler for event type: {event_type}")
            for route in routes:
                active_route = route
                async with self.session_factory() as session:
                    await consume_once(
                        session,
                        route.consumer_name,
                        envelope,
                        route.handler,
                        defer_idempotency=route.defer_idempotency,
                    )
        except Exception as error:
            malformed = not envelope or not envelope.get("event_type")
            if malformed or attempts >= self.max_attempts:
                if active_route is not None and active_route.terminal_failure_handler is not None:
                    async with self.session_factory() as session:
                        await active_route.terminal_failure_handler(session, envelope)
                        await session.commit()
                await self.broker.publish_dead_letter(
                    envelope or {"event_type": "worker.malformed_event"},
                    reason=str(error),
                    attempts=attempts,
                )
                await message.ack()
                return
            await message.reject(requeue=False)
            return
        await message.ack()
