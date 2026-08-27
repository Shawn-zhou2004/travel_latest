import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_generation_job_create_uses_selected_destination_contract() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="generation-job-router-test")
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        try:
            with TestClient(app) as client:
                phone = "13600000022"
                # SMS login requires an existing account; create it directly.
                async with session_factory() as seed:
                    seed.add(User(phone=phone))
                    await seed.commit()
                assert client.post("/api/v1/auth/sms-codes", json={"phone": phone}).status_code == 202
                code = auth.store.get(f"auth:sms:{phone}")
                assert code is not None
                token = client.post(
                    "/api/v1/auth/sessions",
                    json={"phone": phone, "code": code, "device_name": "test"},
                ).json()["access_token"]
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": "generation-job-router-key",
                }
                response = client.post(
                    "/api/v1/generation-jobs",
                    headers=headers,
                    json={
                        "destination": {
                            "name": "长沙市",
                            "display_address": "中国 · 湖南省 · 长沙市",
                            "city_code": "430100",
                        },
                        "start_date": "2026-10-01",
                        "end_date": "2026-10-03",
                        "preference_tags": ["吃吃喝喝", "citywalk"],
                    },
                )
                assert response.status_code == 201
                assert response.json()["status"] == "queued"

                exhausted = client.post(
                    "/api/v1/generation-jobs",
                    headers={**headers, "Idempotency-Key": "generation-job-router-exhausted"},
                    json={
                        "destination": {"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
                        "start_date": "2026-10-01", "end_date": "2026-10-03",
                    },
                )
                assert exhausted.status_code == 429
                assert exhausted.json()["code"] == "AI_QUOTA_EXHAUSTED"
                assert exhausted.json()["details"]["remaining"] == 0
                assert exhausted.json()["details"]["upgrade_available"] is True

                legacy_response = client.post(
                    "/api/v1/generation-jobs",
                    headers={**headers, "Idempotency-Key": "legacy-city-code-key"},
                    json={
                        "city_code": "430100",
                        "start_date": "2026-10-01",
                        "end_date": "2026-10-01",
                    },
                )
                assert legacy_response.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(scenario())
