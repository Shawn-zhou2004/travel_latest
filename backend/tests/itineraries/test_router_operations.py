import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.models.user import User
from app.main import create_app
from app.models.base import Base
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_operations_route_returns_applied_result() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth_service = AuthService(InMemoryTTLStore(), secret="router-test-secret")
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth_service

        try:
            with TestClient(app) as client:
                phone = "13600000009"
                # SMS login requires an existing account; create it directly.
                async with session_factory() as seed:
                    seed.add(User(phone=phone))
                    await seed.commit()
                response = client.post("/api/v1/auth/sms-codes", json={"phone": phone})
                assert response.status_code == 202
                code = auth_service.store.get(f"auth:sms:{phone}")
                assert code is not None

                response = client.post(
                    "/api/v1/auth/sessions",
                    json={"phone": phone, "code": code, "device_name": "router-test"},
                )
                assert response.status_code == 201
                token = response.json()["access_token"]

                response = client.post(
                    "/api/v1/itineraries",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"title": "Router test", "start_date": "2026-10-01", "end_date": "2026-10-03"},
                )
                assert response.status_code == 201
                itinerary_id = response.json()["id"]

                response = client.post(
                    f"/api/v1/itineraries/{itinerary_id}:operations",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "If-Match-Version": "1",
                        "X-Operation-ID": str(uuid.uuid4()),
                    },
                    json={"operation_type": "add_day", "payload": {"day_date": "2026-10-01"}},
                )

                assert response.status_code == 200
                assert response.json()["code"] == "APPLIED"
                assert response.json()["current_version"] == 2
                assert len(response.json()["snapshot"]["days"]) == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())
