import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base, utc_now
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.notifications.models import Notification
from app.modules.chat.models import Conversation, ConversationMember, Message


def test_consumer_notification_list_and_read_operations_are_private_and_idempotent() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        import app.models.user  # noqa: F401
        import app.modules.notifications.models  # noqa: F401

        async with engine.begin() as connection:
            import app.modules.chat.models  # noqa: F401
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth_service = AuthService(InMemoryTTLStore(), secret="notifications-router-test-secret")
        owner_id = "f15ae2ae-1a49-4531-9668-2db8c01772cb"
        other_id = "fef2c6b7-8cff-4527-a2b5-a1fcd62a4bd5"

        async with session_factory() as session:
            oldest = Notification(
                user_id=owner_id,
                notification_type="message.created",
                payload_json={"secret": "do not expose"},
                created_at=utc_now() - timedelta(minutes=2),
            )
            newest = Notification(
                user_id=owner_id,
                notification_type="travel_order.created",
                payload_json={"payment_reference": "private"},
                created_at=utc_now() - timedelta(minutes=1),
            )
            other = Notification(
                user_id=other_id,
                notification_type="message.created",
                payload_json={"body": "private"},
            )
            session.add_all([oldest, newest, other])
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth_service
        try:
            with TestClient(app) as client:
                owner_headers = _headers(auth_service, owner_id)
                other_headers = _headers(auth_service, other_id)
                admin_headers = _admin_headers(auth_service, owner_id)
                assert client.get("/api/v1/notifications", headers=admin_headers).status_code == 403
                listed = client.get("/api/v1/notifications?limit=1", headers=owner_headers)
                assert listed.status_code == 200
                assert listed.json()["items"] == [
                        {
                            "id": newest.id,
                            "notification_type": "travel_order.created",
                            "created_at": newest.created_at.isoformat().replace("+00:00", "Z"),
                            "read_at": None,
                            "payload": {"payment_reference": "private"},
                        }
                    ]
                assert listed.json()["next_cursor"] == newest.id
                assert "payload_json" not in listed.json()["items"][0]
                summary = client.get("/api/v1/notifications/summary", headers=owner_headers)
                assert summary.json() == {"groups": [], "total_unread": 0}

                page_two = client.get(f"/api/v1/notifications?cursor={newest.id}", headers=owner_headers)
                assert page_two.status_code == 200
                assert [item["id"] for item in page_two.json()["items"]] == [oldest.id]
                assert client.get(f"/api/v1/notifications?cursor={other.id}", headers=owner_headers).status_code == 400
                assert client.get("/api/v1/notifications?limit=51", headers=owner_headers).status_code == 422

                denied = client.post(
                    "/api/v1/notifications:mark-read", headers=owner_headers, json={"notification_ids": [other.id]}
                )
                assert denied.json() == {"updated_count": 0}
                first_read = client.post(
                    "/api/v1/notifications:mark-read", headers=owner_headers, json={"notification_ids": [newest.id]}
                )
                assert first_read.json() == {"updated_count": 1}
                second_read = client.post(
                    "/api/v1/notifications:mark-read", headers=owner_headers, json={"notification_ids": [newest.id]}
                )
                assert second_read.json() == {"updated_count": 0}

                unread = client.get("/api/v1/notifications?unread_only=true", headers=owner_headers)
                assert [item["id"] for item in unread.json()["items"]] == [oldest.id]
                all_read = client.post("/api/v1/notifications:mark-read", headers=owner_headers, json={})
                assert all_read.json() == {"updated_count": 1}
                assert client.post("/api/v1/notifications:mark-read", headers=owner_headers, json={}).json() == {"updated_count": 0}
                assert client.get("/api/v1/notifications?unread_only=true", headers=owner_headers).json()["items"] == []
                assert client.get("/api/v1/notifications", headers=other_headers).json()["items"][0]["id"] == other.id
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _headers(auth_service: AuthService, user_id: str) -> dict[str, str]:
    token = auth_service.create_access_token(user_id=user_id, audience="consumer", roles=["user"])
    return {"Authorization": f"Bearer {token}"}


def _admin_headers(auth_service: AuthService, user_id: str) -> dict[str, str]:
    token = auth_service.create_access_token(user_id=user_id, audience="admin", roles=["platform_admin"])
    return {"Authorization": f"Bearer {token}"}
