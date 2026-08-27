import asyncio
from collections.abc import AsyncIterator
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.models.user import User
from app.main import create_app
from app.models.base import Base
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_manual_plan_creates_date_skeleton() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="manual-plan-router-test")
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        try:
            with TestClient(app) as client:
                phone = "13600000002"
                # SMS login requires an existing account; create it directly.
                async with session_factory() as seed:
                    seed.add(User(phone=phone))
                    await seed.commit()
                assert client.post("/api/v1/auth/sms-codes", json={"phone": phone}).status_code == 202
                code = auth.store.get(f"auth:sms:{phone}")
                assert code is not None
                session_response = client.post("/api/v1/auth/sessions", json={"phone": phone, "code": code, "device_name": "test"})
                token = session_response.json()["access_token"]
                response = client.post("/api/v1/itineraries:manual-plan", headers={"Authorization": f"Bearer {token}"}, json={
                    "destination": {"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
                    "start_date": "2026-10-01", "end_date": "2026-10-03", "title": "长沙三日游",
                })
                assert response.status_code == 201
                itinerary = response.json()
                detail = client.get(f"/api/v1/itineraries/{itinerary['id']}", headers={"Authorization": f"Bearer {token}"})
                assert [day["day_date"] for day in detail.json()["snapshot"]["days"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
                assert all(day["events"] == [] for day in detail.json()["snapshot"]["days"])
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_manual_plan_rejects_invalid_dates_and_requires_consumer_auth() -> None:
    app = create_app()
    with TestClient(app) as client:
        unauthenticated = client.post("/api/v1/itineraries:manual-plan", json={
            "destination": {"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
            "start_date": "2026-10-01", "end_date": "2026-10-03",
        })
    assert unauthenticated.status_code == 401

    auth = AuthService(InMemoryTTLStore())
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    headers = {"Authorization": f"Bearer {auth.create_access_token(user_id='consumer-1', audience='consumer', roles=['user'])}"}
    with TestClient(app) as client:
        reversed_dates = client.post("/api/v1/itineraries:manual-plan", headers=headers, json={
            "destination": {"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
            "start_date": "2026-10-03", "end_date": "2026-10-01",
        })
        past_start = client.post("/api/v1/itineraries:manual-plan", headers=headers, json={
            "destination": {"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
            "start_date": (date.today() - timedelta(days=1)).isoformat(), "end_date": date.today().isoformat(),
        })
    assert reversed_dates.status_code == 422
    assert past_start.status_code == 422


def test_delete_itinerary_requires_owner() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="delete-router-test")
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        try:
            with TestClient(app) as client:
                phone, other_phone = "13600000021", "13600000022"
                # SMS login requires an existing account; create both directly.
                async with session_factory() as seed:
                    seed.add(User(phone=phone))
                    seed.add(User(phone=other_phone))
                    await seed.commit()
                for current_phone in (phone, other_phone):
                    assert client.post("/api/v1/auth/sms-codes", json={"phone": current_phone}).status_code == 202
                owner_code = auth.store.get(f"auth:sms:{phone}")
                other_code = auth.store.get(f"auth:sms:{other_phone}")
                owner_token = client.post("/api/v1/auth/sessions", json={"phone": phone, "code": owner_code, "device_name": "test"}).json()["access_token"]
                other_token = client.post("/api/v1/auth/sessions", json={"phone": other_phone, "code": other_code, "device_name": "test"}).json()["access_token"]
                headers = {"Authorization": f"Bearer {owner_token}"}
                created = client.post("/api/v1/itineraries", headers=headers, json={
                    "title": "Delete confirmation", "start_date": "2026-10-01", "end_date": "2026-10-01",
                })
                itinerary_id = created.json()["id"]
                forbidden = client.request("DELETE", f"/api/v1/itineraries/{itinerary_id}", headers={"Authorization": f"Bearer {other_token}"})
                assert forbidden.status_code == 403
                deleted = client.request("DELETE", f"/api/v1/itineraries/{itinerary_id}", headers=headers)
                assert deleted.status_code == 204 and deleted.content == b""
                assert client.get(f"/api/v1/itineraries/{itinerary_id}", headers=headers).status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(scenario())
