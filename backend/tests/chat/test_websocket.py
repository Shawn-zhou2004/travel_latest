import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.chat.schemas import MessageCreate
from app.modules.chat.websocket import ConversationHub


class FakeSubscription:
    def __init__(self, broker: "FakeRedis") -> None:
        self.broker = broker
        self.channels: set[str] = set()
        self.messages: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channels.add(channel)
        self.broker.subscribers.setdefault(channel, set()).add(self)

    async def unsubscribe(self, channel: str) -> None:
        self.channels.discard(channel)
        self.broker.subscribers.get(channel, set()).discard(self)

    async def get_message(self, **_: object) -> dict[str, object] | None:
        try:
            return await asyncio.wait_for(self.messages.get(), 0.05)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self) -> None:
        self.subscribers: dict[str, set[FakeSubscription]] = {}
        self.published: list[tuple[str, str]] = []

    def pubsub(self) -> FakeSubscription:
        return FakeSubscription(self)

    async def publish(self, channel: str, data: str) -> None:
        self.published.append((channel, data))
        for subscription in tuple(self.subscribers.get(channel, ())):
            await subscription.messages.put({"type": "message", "data": data})


def test_realtime_ticket_reveals_bound_user_once_without_user_query_parameter() -> None:
    service = AuthService(InMemoryTTLStore(), secret="websocket-test")
    ticket = service.create_realtime_ticket("user-1", "conversation", "conversation-1")

    assert service.consume_realtime_ticket_for_resource(ticket, "conversation", "conversation-1") == "user-1"
    assert service.consume_realtime_ticket_for_resource(ticket, "conversation", "conversation-1") is None


def test_redis_hub_broadcasts_between_two_listeners_and_cleans_subscriptions() -> None:
    async def scenario() -> None:
        redis = FakeRedis()
        first_hub = ConversationHub(lambda: redis)
        second_hub = ConversationHub(lambda: redis)
        first = await first_hub.subscribe("conversation-1")
        second = await second_hub.subscribe("conversation-1")
        event = {"type": "message.created", "message": {"id": "message-1"}}

        await first_hub.publish("conversation-1", event)

        assert await first_hub.next_event(first, 0.1) == event
        assert await second_hub.next_event(second, 0.1) == event
        assert redis.published == [("chat:conversation:conversation-1", json.dumps(event, separators=(",", ":")))]
        await first_hub.disconnect("conversation-1", first)
        await second_hub.disconnect("conversation-1", second)
        assert not redis.subscribers["chat:conversation:conversation-1"]
        assert first.closed and second.closed

    asyncio.run(scenario())


@pytest.mark.anyio
async def test_message_commit_precedes_publish_and_publish_failure_does_not_fail_response(monkeypatch) -> None:
    from app.modules.chat import router as chat_router

    operations: list[str] = []
    message = SimpleNamespace(
        id="message-1",
        conversation_id="conversation-1",
        sender_id="user-1",
        client_message_id="client-1",
        message_type="text",
        body_text="hello",
        payload_json=None,
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    class Service:
        def __init__(self, _: object) -> None:
            pass

        async def create_message(self, *_: object) -> object:
            operations.append("persist")
            return message

    class Session:
        async def commit(self) -> None:
            operations.append("commit")

    async def publish(_: str, event: dict[str, object]) -> None:
        operations.append("publish")
        assert event["type"] == "message.created"
        assert event["message"]["id"] == "message-1"  # type: ignore[index]
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(chat_router, "ChatService", Service)
    monkeypatch.setattr(chat_router.conversation_hub, "publish", publish)

    response = await chat_router.send_message(
        "conversation-1",
        MessageCreate(client_message_id="client-1", message_type="text", body_text="hello"),
        SimpleNamespace(user_id="user-1"),
        Session(),
    )

    assert operations == ["persist", "commit", "publish"]
    assert response.id == "message-1"
