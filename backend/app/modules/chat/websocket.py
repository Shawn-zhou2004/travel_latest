import asyncio
import json
from contextlib import suppress
from typing import Any, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.settings import Settings
from app.modules.auth.dependencies import get_auth_service
from app.modules.chat.models import ConversationMember


websocket_router = APIRouter(tags=["chat"])


class ConversationHub:
    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory or self._configured_client
        self._client: Any | None = None

    @staticmethod
    def _configured_client() -> Redis:
        redis_url = Settings().redis_url
        if not redis_url:
            raise RuntimeError("REDIS_URL is required for chat realtime delivery")
        # This is called lazily in the serving process, never in uvicorn's reload parent.
        return Redis.from_url(redis_url, decode_responses=True)

    def _redis(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    @staticmethod
    def channel(conversation_id: str) -> str:
        return f"chat:conversation:{conversation_id}"

    async def subscribe(self, conversation_id: str) -> Any:
        subscription = self._redis().pubsub()
        try:
            await subscription.subscribe(self.channel(conversation_id))
        except Exception:
            await subscription.aclose()
            raise
        return subscription

    async def disconnect(self, conversation_id: str, subscription: Any) -> None:
        with suppress(Exception):
            await subscription.unsubscribe(self.channel(conversation_id))
        with suppress(Exception):
            await subscription.aclose()

    async def publish(self, conversation_id: str, event: dict[str, Any]) -> None:
        await self._redis().publish(
            self.channel(conversation_id),
            json.dumps(event, separators=(",", ":")),
        )

    async def next_event(self, subscription: Any, timeout: float) -> dict[str, Any] | None:
        message = await subscription.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if message is None or message.get("type") != "message":
            return None
        data = message.get("data")
        if isinstance(data, bytes):
            data = data.decode()
        event = json.loads(data)
        return event if isinstance(event, dict) else None


conversation_hub = ConversationHub()


@websocket_router.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: str, ticket: str) -> None:
    """Authenticate and authorize before accepting, then bridge one Redis channel."""
    user_id = get_auth_service().consume_realtime_ticket_for_resource(ticket, "conversation", conversation_id)
    if user_id is None:
        await websocket.close(code=1008)
        return
    async with SessionLocal() as session:
        member = await session.scalar(select(ConversationMember.id).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        ))
    if member is None:
        await websocket.close(code=1008)
        return

    try:
        subscription = await conversation_hub.subscribe(conversation_id)
    except Exception:
        await websocket.close(code=1013)
        return
    await websocket.accept()

    async def send_events() -> None:
        while True:
            event = await conversation_hub.next_event(subscription, timeout=25)
            await websocket.send_json(event or {"type": "ping"})

    async def receive_events() -> None:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
            # "pong" acknowledges the server heartbeat and needs no response.

    sender = asyncio.create_task(send_events())
    receiver = asyncio.create_task(receive_events())
    try:
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            try:
                task.result()
            except WebSocketDisconnect:
                pass
            except Exception:
                with suppress(Exception):
                    await websocket.close(code=1011)
    finally:
        sender.cancel()
        receiver.cancel()
        for task in (sender, receiver):
            with suppress(asyncio.CancelledError, WebSocketDisconnect):
                await task
        await conversation_hub.disconnect(conversation_id, subscription)
