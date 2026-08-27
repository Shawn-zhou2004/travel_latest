import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth.dependencies import CurrentConsumer
from app.modules.chat.models import Message
from app.modules.chat.schemas import BlockCreate, ConversationListResponse, ConversationResponse, DirectConversationCreate, MessageCreate, MessageListResponse, MessageResponse
from app.modules.chat.service import ChatError, ChatService
from app.modules.chat.websocket import conversation_hub


router = APIRouter(tags=["chat"])
Session = Annotated[AsyncSession, Depends(get_session)]
logger = logging.getLogger(__name__)


def _error(error: ChatError) -> HTTPException:
    return HTTPException(403 if error.code in {"USER_BLOCKED", "NOT_CONVERSATION_MEMBER"} else 404 if error.code == "CONVERSATION_NOT_FOUND" else 409, detail={"code": error.code, "message": error.message})


@router.post("/conversations/direct", status_code=status.HTTP_201_CREATED)
async def open_direct(body: DirectConversationCreate, claims: CurrentConsumer, session: Session) -> dict[str, str]:
    try:
        conversation = await ChatService(session).open_direct(claims.user_id, body.user_id)
        await session.commit()
        return {"id": conversation.id}
    except ChatError as error:
        raise _error(error) from error


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(claims: CurrentConsumer, session: Session, cursor: str | None = None, limit: int = 20) -> ConversationListResponse:
    rows, next_cursor = await ChatService(session).list_conversations(claims.user_id, cursor, max(1, min(limit, 50)))
    return ConversationListResponse(items=[ConversationResponse(
        id=conversation.id,
        conversation_type=conversation.conversation_type,
        title=conversation.title,
        avatar_asset_id=conversation.avatar_asset_id,
        unread_count=unread_count,
        last_message=MessageResponse.model_validate(last_message) if last_message else None,
    ) for conversation, unread_count, last_message in rows], next_cursor=next_cursor)


@router.get("/conversations/{conversation_id}/messages", response_model=MessageListResponse)
async def message_history(conversation_id: str, claims: CurrentConsumer, session: Session, cursor: str | None = None, limit: int = 50) -> MessageListResponse:
    try:
        messages, next_cursor = await ChatService(session).list_messages(conversation_id, claims.user_id, cursor, max(1, min(limit, 100)))
        await session.commit()
        return MessageListResponse(items=[MessageResponse.model_validate(item) for item in messages], next_cursor=next_cursor)
    except ChatError as error:
        raise _error(error) from error


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(conversation_id: str, body: MessageCreate, claims: CurrentConsumer, session: Session) -> MessageResponse:
    try:
        message = await ChatService(session).create_message(conversation_id, claims.user_id, body.client_message_id, body.message_type, body.body_text, body.payload_json)
        await session.commit()
        response = MessageResponse.model_validate(message)
        event = {
            "type": "message.created",
            "conversation_id": conversation_id,
            "message": response.model_dump(mode="json"),
        }
        try:
            await conversation_hub.publish(conversation_id, event)
        except Exception:
            # Persistence is authoritative; reconnecting clients recover this gap from history.
            logger.exception("Failed to publish message.created", extra={"conversation_id": conversation_id, "message_id": message.id})
        return response
    except ChatError as error:
        raise _error(error) from error


@router.post("/blocks", status_code=status.HTTP_201_CREATED)
async def block_user(body: BlockCreate, claims: CurrentConsumer, session: Session) -> dict[str, str]:
    try:
        block = await ChatService(session).block(claims.user_id, body.user_id)
        await session.commit()
        return {"id": block.id}
    except ChatError as error:
        raise _error(error) from error


@router.delete("/blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_user(user_id: str, claims: CurrentConsumer, session: Session) -> None:
    await ChatService(session).unblock(claims.user_id, user_id)
    await session.commit()


@router.post("/conversations/{conversation_id}:leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_conversation(conversation_id: str, claims: CurrentConsumer, session: Session) -> None:
    try:
        await ChatService(session).leave_conversation(conversation_id, claims.user_id)
        await session.commit()
    except ChatError as error:
        raise _error(error) from error
