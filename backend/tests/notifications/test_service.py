import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base, utc_now
from app.models.user import User, UserSettings
from app.modules.notifications.models import Notification
from app.modules.chat.models import Conversation, ConversationMember, Message
from app.modules.chat.service import ChatService
from app.modules.notifications.router import list_notifications
from app.modules.notifications.service import NotificationService
from app.workers.domain_handlers import _notify_user


def test_notification_service_scopes_pages_and_read_updates_to_owner() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        import app.models.user  # noqa: F401
        import app.modules.notifications.models  # noqa: F401

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        owner_id = "f15ae2ae-1a49-4531-9668-2db8c01772cb"
        other_id = "fef2c6b7-8cff-4527-a2b5-a1fcd62a4bd5"
        async with session_factory() as session:
            oldest = Notification(
                user_id=owner_id,
                notification_type="message.created",
                payload_json={},
                created_at=utc_now() - timedelta(minutes=2),
            )
            newest = Notification(
                user_id=owner_id,
                notification_type="travel_order.created",
                payload_json={},
                created_at=utc_now() - timedelta(minutes=1),
            )
            other = Notification(user_id=other_id, notification_type="message.created", payload_json={})
            session.add_all([oldest, newest, other])
            await session.commit()

            service = NotificationService(session)
            first_page, next_cursor = await service.list_for_user(owner_id, cursor=None, limit=1, unread_only=False)
            assert [notification.id for notification in first_page] == [newest.id]
            assert next_cursor == newest.id
            second_page, next_cursor = await service.list_for_user(owner_id, cursor=next_cursor, limit=1, unread_only=False)
            assert [notification.id for notification in second_page] == [oldest.id]
            assert next_cursor is None

            assert await service.mark_read(owner_id, [newest.id, other.id]) == 1
            assert await service.mark_read(owner_id, [newest.id]) == 0
            assert await service.mark_read(owner_id, None) == 1
            assert await service.mark_read(owner_id, None) == 0
            await session.commit()
            assert other.read_at is None
        await engine.dispose()

    asyncio.run(scenario())


def test_group_unread_summary_aggregates_only_active_companion_groups() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        import app.models.user  # noqa: F401
        import app.modules.chat.models  # noqa: F401
        import app.modules.notifications.models  # noqa: F401

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        owner_id = "f15ae2ae-1a49-4531-9668-2db8c01772cb"
        sender_id = "fef2c6b7-8cff-4527-a2b5-a1fcd62a4bd5"
        async with session_factory() as session:
            now = utc_now()
            group = Conversation(id="11111111-1111-4111-8111-111111111111", conversation_type="companion_group", title="川西同行", avatar_asset_id=None)
            direct = Conversation(id="22222222-2222-4222-8222-222222222222", conversation_type="direct")
            session.add_all([
                group,
                direct,
                ConversationMember(conversation_id=group.id, user_id=owner_id, joined_at=now),
                ConversationMember(conversation_id=group.id, user_id=sender_id, joined_at=now),
                ConversationMember(conversation_id=direct.id, user_id=owner_id, joined_at=now),
                Message(id="33333333-3333-4333-8333-333333333333", conversation_id=group.id, sender_id=sender_id, client_message_id="m-1", message_type="text", body_text="明早出发", created_at=now + timedelta(seconds=1)),
                Notification(user_id=owner_id, notification_type="companion_application.accepted", payload_json={"conversation_id": group.id}),
            ])
            await session.commit()

            summary = await NotificationService(session).group_unread_summary(owner_id)
            assert [(conversation.title, unread, message.body_text) for conversation, unread, message in summary] == [("川西同行", 1, "明早出发")]

            await ChatService(session).list_messages(group.id, owner_id)
            await session.commit()
            assert await NotificationService(session).group_unread_summary(owner_id) == []

        await engine.dispose()

    asyncio.run(scenario())


def test_worker_notifications_respect_master_and_category_settings() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        import app.models.user  # noqa: F401
        import app.modules.notifications.models  # noqa: F401

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(id="f15ae2ae-1a49-4531-9668-2db8c01772cb", phone="13700000101")
            session.add_all([user, UserSettings(user_id=user.id, notifications_enabled=False)])
            await session.commit()

            await _notify_user(session, {
                "event_type": "companion_application.accepted",
                "payload": {"applicant_id": user.id},
            })
            await session.flush()
            assert await session.scalar(select(Notification).where(Notification.user_id == user.id)) is None

            settings = await session.get(UserSettings, user.id)
            assert settings is not None
            settings.notifications_enabled = True
            settings.itinerary_notifications = False
            await session.commit()

            await _notify_user(session, {
                "event_type": "itinerary.export.completed",
                "payload": {"user_id": user.id},
            })
            await _notify_user(session, {
                "event_type": "travel_order.created",
                "payload": {"user_id": user.id},
            })
            await session.flush()
            notifications = list((await session.scalars(select(Notification).where(Notification.user_id == user.id))).all())
            assert [notification.notification_type for notification in notifications] == ["travel_order.created"]
        await engine.dispose()

    asyncio.run(scenario())


def test_notification_api_exposes_existing_companion_request_payload() -> None:
    class Claims:
        user_id = "f15ae2ae-1a49-4531-9668-2db8c01772cb"

    class Session:
        pass

    notification = Notification(
        id="11111111-1111-4111-8111-111111111111",
        user_id=Claims.user_id,
        notification_type="companion_application.created",
        payload_json={"request_id": "plan-1", "applicant_id": "user-2"},
        created_at=utc_now(),
    )

    async def list_for_user(self, user_id, *, cursor, limit, unread_only):
        assert (user_id, cursor, limit, unread_only) == (Claims.user_id, None, 20, False)
        return [notification], None

    original = NotificationService.list_for_user
    NotificationService.list_for_user = list_for_user
    try:
        response = asyncio.run(list_notifications(Claims(), Session(), limit=20))
    finally:
        NotificationService.list_for_user = original

    assert response.items[0].payload == {"request_id": "plan-1", "applicant_id": "user-2"}
