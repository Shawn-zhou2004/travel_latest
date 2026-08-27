import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.modules.admin import router as admin_router
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.ai_workflows.models import GenerationJob
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.exports.models import ExportTask


def test_platform_admin_can_read_deidentified_ai_workflow_health() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-ai-health-test-secret")
        latest = datetime(2026, 8, 6, 9, 30, tzinfo=UTC)
        async with factory() as session:
            admin = User(phone="13600000026")
            session.add(admin)
            await session.flush()
            session.add_all([
                GenerationJob(user_id=admin.id, idempotency_key="health-queued", city_code="330100", prompt="private prompt", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7), request_json={}, status="queued"),
                GenerationJob(user_id=admin.id, idempotency_key="health-running", city_code="330100", prompt="private prompt", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7), request_json={}, status="planning"),
                GenerationJob(user_id=admin.id, idempotency_key="health-failed", city_code="330100", prompt="private prompt", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7), request_json={}, status="failed", updated_at=latest),
                ExportTask(requester_id=admin.id, itinerary_id="00000000-0000-4000-8000-000000000001", itinerary_version_id="00000000-0000-4000-8000-000000000002", version_no=1, idempotency_key="health-queued", snapshot_json={}),
                ExportTask(requester_id=admin.id, itinerary_id="00000000-0000-4000-8000-000000000003", itinerary_version_id="00000000-0000-4000-8000-000000000004", version_no=1, idempotency_key="health-running", snapshot_json={}, status="running"),
                ExportTask(requester_id=admin.id, itinerary_id="00000000-0000-4000-8000-000000000005", itinerary_version_id="00000000-0000-4000-8000-000000000006", version_no=1, idempotency_key="health-failed", snapshot_json={}, status="failed", updated_at=latest),
                OutboxEvent(event_type="ai.private", aggregate_type="generation_job", aggregate_id="00000000-0000-4000-8000-000000000007", trace_id="00000000-0000-4000-8000-000000000008", payload_json={}),
                OutboxEvent(event_type="ai.private", aggregate_type="generation_job", aggregate_id="00000000-0000-4000-8000-000000000009", trace_id="00000000-0000-4000-8000-000000000010", payload_json={}, retry_count=2, updated_at=latest),
                OutboxEvent(event_type="ai.private", aggregate_type="generation_job", aggregate_id="00000000-0000-4000-8000-000000000011", trace_id="00000000-0000-4000-8000-000000000012", payload_json={}, published_at=latest),
            ])
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        original_worker_health = admin_router._worker_heartbeat_health

        async def test_worker_health() -> admin_router.WorkerHeartbeatHealth:
            return admin_router.WorkerHeartbeatHealth(status="unavailable", last_heartbeat_at=None)

        admin_router._worker_heartbeat_health = test_worker_health
        admin_token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        consumer_token = auth.create_access_token(user_id=admin.id, audience="consumer", roles=["user"])
        try:
            with TestClient(app) as client:
                denied = client.get("/api/v1/admin/ai/workflow-health", headers={"Authorization": f"Bearer {consumer_token}"})
                assert denied.status_code == 403
                response = client.get("/api/v1/admin/ai/workflow-health", headers={"Authorization": f"Bearer {admin_token}"})
                assert response.status_code == 200
                body = response.json()
                assert body["generation_jobs"] | {"most_recent_at": None} == {"queued": 1, "running": 1, "failed": 1, "most_recent_at": None}
                assert body["export_tasks"] | {"most_recent_at": None} == {"queued": 1, "running": 1, "failed": 1, "most_recent_at": None}
                assert body["outbox"] | {"most_recent_at": None} == {"unprocessed": 1, "retrying": 1, "dead_letter": 0, "most_recent_at": None}
                assert body["worker"] == {"status": "unavailable", "last_heartbeat_at": None}
                assert all(body[key]["most_recent_at"] for key in ("generation_jobs", "export_tasks", "outbox"))
                assert "private prompt" not in response.text
                assert "ai.private" not in response.text
        finally:
            admin_router._worker_heartbeat_health = original_worker_health
            await engine.dispose()

    asyncio.run(scenario())
