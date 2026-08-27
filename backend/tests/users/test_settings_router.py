import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User, UserSettings
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.ai_memory.router import get_ai_memory_service


def test_user_settings_defaults_are_product_defaults() -> None:
    settings = UserSettings(user_id="00000000-0000-4000-8000-000000000001")

    assert settings.budget_level == "balanced"
    assert settings.travel_pace == "balanced"
    assert settings.traveler_type == "friends"
    assert settings.interest_tags == []
    assert settings.notifications_enabled is True
    assert settings.order_notifications is True
    assert settings.itinerary_notifications is True
    assert settings.community_notifications is True
    assert settings.profile_visibility == "collaborators"


def test_settings_routes_create_update_validate_and_isolate_settings() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="settings-test-secret")
        async with factory() as session:
            user = User(phone="13800000011")
            other_user = User(phone="13800000012")
            session.add_all([user, other_user])
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=user.id, audience='consumer', roles=['user'])}"}
        other_headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=other_user.id, audience='consumer', roles=['user'])}"}
        with TestClient(app) as client:
            initial = client.get("/api/v1/users/me/settings", headers=headers)
            assert initial.status_code == 200
            assert initial.json()["budget_level"] == "balanced"
            assert initial.json()["interest_tags"] == []

            first = client.patch(
                "/api/v1/users/me/settings",
                headers=headers,
                json={"departure_city": " 杭州 ", "travel_pace": "relaxed", "interest_tags": ["吃吃喝喝"]},
            )
            second = client.patch(
                "/api/v1/users/me/settings",
                headers=headers,
                json={"community_notifications": False},
            )
            assert first.status_code == second.status_code == 200
            assert second.json()["departure_city"] == "杭州"
            assert second.json()["travel_pace"] == "relaxed"
            assert second.json()["interest_tags"] == ["吃吃喝喝"]
            assert second.json()["community_notifications"] is False

            cleared = client.patch(
                "/api/v1/users/me/settings",
                headers=headers,
                json={"departure_city": "", "interest_tags": []},
            )
            assert cleared.status_code == 200
            assert cleared.json()["departure_city"] is None
            assert cleared.json()["interest_tags"] == []

            assert client.patch("/api/v1/users/me/settings", headers=headers, json={}).status_code == 422
            assert client.patch("/api/v1/users/me/settings", headers=headers, json={"budget_level": "luxury"}).status_code == 422
            assert client.patch("/api/v1/users/me/settings", headers=headers, json={"budget_level": None}).status_code == 422
            assert client.patch("/api/v1/users/me/settings", headers=headers, json={"interest_tags": ["invalid"]}).status_code == 422
            assert client.patch("/api/v1/users/me/settings", headers=headers, json={"interest_tags": ["吃吃喝喝", "吃吃喝喝"]}).status_code == 422

            isolated = client.get("/api/v1/users/me/settings", headers=other_headers)
            assert isolated.status_code == 200
            assert isolated.json()["departure_city"] is None
            assert isolated.json()["community_notifications"] is True

            other_update = client.patch(
                "/api/v1/users/me/settings",
                headers=other_headers,
                json={"departure_city": "上海"},
            )
            assert other_update.status_code == 200
            assert other_update.json()["departure_city"] == "上海"
            original = client.get("/api/v1/users/me/settings", headers=headers)
            assert original.json()["departure_city"] is None

        await engine.dispose()

    asyncio.run(scenario())


def test_sync_settings_to_ai_memory_uses_mysql_settings_and_isolates_users() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="sync-test-secret")
        async with factory() as session:
            user = User(phone="13800000021")
            other_user = User(phone="13800000022")
            session.add_all([user, other_user])
            await session.flush()
            session.add(UserSettings(user_id=user.id, departure_city="苏州", interest_tags=["citywalk"], travel_pace="relaxed", traveler_type="family"))
            await session.commit()

        class FakeMemoryService:
            def __init__(self) -> None:
                self.values: dict[str, dict[str, object]] = {}
                self.ids: dict[str, str] = {}

            async def sync_travel_profile(self, user_id: str, value: dict[str, object]) -> dict[str, object]:
                self.values[user_id] = value
                self.ids.setdefault(user_id, f"memory-{user_id}")
                now = datetime.now(UTC)
                return {"id": self.ids[user_id], "memory_type": "profile", "memory_key": "travel_profile", "memory_value": value, "source": "user_settings", "confidence": 1.0, "created_at": now, "updated_at": now}

        memory_service = FakeMemoryService()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        app.dependency_overrides[get_ai_memory_service] = lambda: memory_service
        headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=user.id, audience='consumer', roles=['user'])}"}
        other_headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=other_user.id, audience='consumer', roles=['user'])}"}
        with TestClient(app) as client:
            first = client.post("/api/v1/users/me/settings:sync-ai-memory", headers=headers, json={"departure_city": "伪造"})
            assert first.status_code == 200
            assert first.json()["memory_value"] == {"departure_city": "苏州", "interest_tags": ["citywalk"], "travel_pace": "relaxed", "traveler_type": "family"}
            await session_update(factory, user.id, {"travel_pace": "packed"})
            second = client.post("/api/v1/users/me/settings:sync-ai-memory", headers=headers)
            other = client.post("/api/v1/users/me/settings:sync-ai-memory", headers=other_headers)
            assert second.json()["id"] == first.json()["id"]
            assert second.json()["memory_value"]["travel_pace"] == "packed"
            assert other.json()["memory_value"]["departure_city"] is None
            assert other.json()["id"] != first.json()["id"]

        await engine.dispose()

    async def session_update(factory: async_sessionmaker[AsyncSession], user_id: str, values: dict[str, object]) -> None:
        async with factory() as session:
            settings = await session.get(UserSettings, user_id)
            for key, value in values.items():
                setattr(settings, key, value)
            await session.commit()

    asyncio.run(scenario())
