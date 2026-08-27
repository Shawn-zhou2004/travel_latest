import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.models.user import User
from app.main import create_app
from app.models.base import Base
from app.modules.ai_entitlements.service import AIEntitlementService
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_ai_entitlements_returns_free_and_active_membership_balances() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="ai-entitlements-router-test")
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        try:
            with TestClient(app) as client:
                phone = "13600000033"
                # SMS login requires an existing account; create it directly.
                async with factory() as seed:
                    seed.add(User(phone=phone))
                    await seed.commit()
                client.post("/api/v1/auth/sms-codes", json={"phone": phone})
                code = auth.store.get(f"auth:sms:{phone}")
                token = client.post("/api/v1/auth/sessions", json={"phone": phone, "code": code, "device_name": "test"}).json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                assert client.get("/api/v1/users/me/ai-entitlements", headers=headers).json() == {
                    "free": {
                        "source": "free", "itinerary_generation_remaining": 1,
                        "assistant_message_remaining": 20,
                        "period_end": client.get("/api/v1/users/me/ai-entitlements", headers=headers).json()["free"]["period_end"],
                    },
                    "membership": None,
                }
        finally:
            await engine.dispose()

    asyncio.run(scenario())
