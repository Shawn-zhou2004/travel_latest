from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth.dependencies import CurrentConsumer
from app.modules.chat.schemas import MessageResponse
from app.modules.notifications.schemas import GroupUnreadSummary, NotificationMarkReadRequest, NotificationMarkReadResponse, NotificationPage, NotificationResponse, UnreadSummaryResponse
from app.modules.notifications.service import NotificationError, NotificationService


router = APIRouter(prefix="/notifications", tags=["notifications"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/summary", response_model=UnreadSummaryResponse)
async def unread_summary(claims: CurrentConsumer, session: Session) -> UnreadSummaryResponse:
    groups = await NotificationService(session).group_unread_summary(claims.user_id)
    return UnreadSummaryResponse(
        groups=[GroupUnreadSummary(
            conversation_id=conversation.id,
            title=conversation.title or "同行群聊",
            avatar_asset_id=conversation.avatar_asset_id,
            unread_count=unread_count,
            last_message=MessageResponse.model_validate(last_message) if last_message else None,
        ) for conversation, unread_count, last_message in groups],
        total_unread=sum(unread_count for _, unread_count, _ in groups),
    )


@router.get("", response_model=NotificationPage)
async def list_notifications(
    claims: CurrentConsumer,
    session: Session,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    unread_only: bool = False,
) -> NotificationPage:
    try:
        notifications, next_cursor = await NotificationService(session).list_for_user(
            claims.user_id, cursor=cursor, limit=limit, unread_only=unread_only
        )
    except NotificationError as error:
        raise HTTPException(400, detail={"code": error.code, "message": error.message}) from error
    return NotificationPage(
        items=[NotificationResponse(
            id=notification.id,
            notification_type=notification.notification_type,
            payload=dict(notification.payload_json),
            created_at=_as_utc(notification.created_at),
            read_at=_as_utc(notification.read_at) if notification.read_at else None,
        ) for notification in notifications],
        next_cursor=next_cursor,
    )


@router.post(":mark-read", response_model=NotificationMarkReadResponse)
async def mark_notifications_read(
    body: NotificationMarkReadRequest, claims: CurrentConsumer, session: Session
) -> NotificationMarkReadResponse:
    updated_count = await NotificationService(session).mark_read(claims.user_id, body.notification_ids)
    await session.commit()
    return NotificationMarkReadResponse(updated_count=updated_count)


def _as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
