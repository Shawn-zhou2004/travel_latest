from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utc_now
from app.modules.notifications.models import Notification
from app.modules.chat.models import Conversation, Message
from app.modules.chat.service import ChatService


class NotificationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: str, notification_type: str, payload_json: dict[str, object]) -> Notification:
        notification = Notification(user_id=user_id, notification_type=notification_type, payload_json=payload_json)
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def list_for_user(
        self, user_id: str, *, cursor: str | None, limit: int, unread_only: bool
    ) -> tuple[list[Notification], str | None]:
        statement = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))
        if cursor:
            cursor_notification = await self.session.scalar(
                select(Notification).where(Notification.id == cursor, Notification.user_id == user_id)
            )
            if cursor_notification is None:
                raise NotificationError("INVALID_CURSOR", "The cursor is unavailable.")
            statement = statement.where(
                (Notification.created_at < cursor_notification.created_at)
                | ((Notification.created_at == cursor_notification.created_at) & (Notification.id < cursor_notification.id))
            )
        notifications = list(
            (
                await self.session.scalars(
                    statement.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
                )
            ).all()
        )
        next_cursor = notifications[limit - 1].id if len(notifications) > limit else None
        return notifications[:limit], next_cursor

    async def mark_read(self, user_id: str, notification_ids: list[str] | None) -> int:
        statement = update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
        if notification_ids is not None:
            statement = statement.where(Notification.id.in_(notification_ids))
        result = await self.session.execute(statement.values(read_at=utc_now()))
        return int(result.rowcount or 0)

    async def unread_count(self, user_id: str) -> int:
        count = await self.session.scalar(select(func.count(Notification.id)).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        ))
        return int(count or 0)

    async def group_unread_summary(self, user_id: str) -> list[tuple[Conversation, int, Message | None]]:
        rows, _ = await ChatService(self.session).list_conversations(user_id, limit=None, conversation_type="companion_group")
        groups = [(conversation, unread_count, last_message) for conversation, unread_count, last_message in rows if unread_count > 0]
        groups.sort(
            key=lambda row: (
                row[2].created_at if row[2] is not None else row[0].updated_at,
                row[2].id if row[2] is not None else row[0].id,
            ),
            reverse=True,
        )
        return groups
