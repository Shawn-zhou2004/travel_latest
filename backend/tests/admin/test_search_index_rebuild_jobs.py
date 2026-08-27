import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import AdminAction, SearchIndexRebuildJob
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_rebuild_job_auth_allowlist_idempotency_and_outbox() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="search-rebuild-test-secret")
        async with factory() as session:
            admin = User(phone="13600000301")
            session.add(admin)
            await session.commit()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['platform_admin'])}"}
        provider_headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['provider_admin'])}"}
        try:
            with TestClient(app) as client:
                assert client.post("/api/v1/admin/search-indexes:rebuild", headers=provider_headers, json={"index_name": "official_knowledge"}).status_code == 403
                assert client.post("/api/v1/admin/search-indexes:rebuild", headers=admin_headers, json={"index_name": "arbitrary"}).status_code == 422
                first = client.post("/api/v1/admin/search-indexes:rebuild", headers=admin_headers, json={"index_name": "user_memory"})
                duplicate = client.post("/api/v1/admin/search-indexes:rebuild", headers=admin_headers, json={"index_name": "user_memory"})
                assert first.status_code == 201
                assert duplicate.status_code == 200
                assert duplicate.json()["id"] == first.json()["id"]
                polled = client.get(f"/api/v1/admin/search-index-rebuild-jobs/{first.json()['id']}", headers=admin_headers)
                assert polled.status_code == 200 and polled.json()["status"] == "queued"
            async with factory() as session:
                job = await session.get(SearchIndexRebuildJob, first.json()["id"])
                events = list((await session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id))).all())
                actions = list((await session.scalars(select(AdminAction).where(AdminAction.target_id == job.id))).all())
                assert job is not None and job.requested_by == admin.id
                assert len(events) == 1 and events[0].event_type == "admin.search_index_rebuild_requested"
                assert len(actions) == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())
