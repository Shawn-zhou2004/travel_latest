import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.exports.models import ExportTask
from app.modules.itineraries.models import Itinerary, ItineraryVersion


def test_platform_admin_lists_export_metadata_without_private_payloads() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-export-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000061")
            consumer = User(phone="13600000062")
            session.add_all([admin, consumer])
            await session.flush()
            itinerary = Itinerary(owner_id=consumer.id, title="Export review", start_date=datetime(2026, 8, 1).date(), end_date=datetime(2026, 8, 2).date())
            session.add(itinerary)
            await session.flush()
            version = ItineraryVersion(itinerary_id=itinerary.id, version=3, snapshot={}, created_by=consumer.id)
            session.add(version)
            await session.flush()
            now = datetime.now(UTC)
            session.add_all([
                ExportTask(
                    requester_id=consumer.id, itinerary_id=itinerary.id, itinerary_version_id=version.id,
                    version_no=3, idempotency_key="failed-task", snapshot_json={"private": "snapshot"},
                    status="failed", progress=40, attempt_count=2, last_attempt_at=now - timedelta(minutes=2),
                    last_error_code="RENDER_FAILED", last_error_message="Document rendering failed.", updated_at=now,
                ),
                ExportTask(
                    requester_id=consumer.id, itinerary_id=itinerary.id, itinerary_version_id=version.id,
                    version_no=3, idempotency_key="success-task", snapshot_json={"private": "snapshot"},
                    status="succeeded", progress=100, attempt_count=1, output_asset_id=None,
                    updated_at=now - timedelta(minutes=1),
                ),
            ])
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        consumer_token = auth.create_access_token(user_id=consumer.id, audience="consumer", roles=["user"])
        try:
            with TestClient(app) as client:
                denied = client.get("/api/v1/admin/export-tasks", headers={"Authorization": f"Bearer {consumer_token}"})
                assert denied.status_code == 403

                response = client.get("/api/v1/admin/export-tasks", params={"status": "failed", "limit": 1}, headers={"Authorization": f"Bearer {admin_token}"})
                assert response.status_code == 200
                body = response.json()
                assert len(body["items"]) == 1
                task = body["items"][0]
                assert task["status"] == "failed"
                assert task["requester_id"] == consumer.id
                assert task["last_error_code"] == "RENDER_FAILED"
                assert {"snapshot_json", "output_asset_id", "object_key", "sha256", "url", "presigned_url"}.isdisjoint(task)

                invalid_limit = client.get("/api/v1/admin/export-tasks", params={"limit": 101}, headers={"Authorization": f"Bearer {admin_token}"})
                assert invalid_limit.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(scenario())
