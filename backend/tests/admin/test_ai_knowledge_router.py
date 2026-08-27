import asyncio
from collections.abc import AsyncIterator
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import OfficialKnowledgeSource, PoiKnowledgeImportJob, StructuredKnowledgeImportJob
from app.modules.ai_workflows.models import GenerationJob
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_admin_can_review_official_knowledge_and_enqueue_indexing() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-ai-knowledge-test-secret")
        async with factory() as setup_session:
            admin = User(phone="13600000019")
            setup_session.add(admin)
            await setup_session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        try:
            with TestClient(app) as client:
                created = client.post(
                    "/api/v1/admin/ai/knowledge-sources",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"source_type": "rule", "title": "West Lake walking rule", "body_text": "Leave time between lakeside stops.", "city_code": "330100"},
                )
                assert created.status_code == 201
                source_id = created.json()["id"]
                reviewed = client.patch(
                    f"/api/v1/admin/ai/knowledge-sources/{source_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "indexed", "reason": "Reviewed and suitable for public retrieval."},
                )
                assert reviewed.status_code == 200
                assert reviewed.json()["status"] == "indexing"
            async with factory() as verify_session:
                source = await verify_session.get(OfficialKnowledgeSource, source_id)
                event = await verify_session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == source_id))
                assert source is not None and source.status == "indexing"
                assert event is not None and event.event_type == "ai.official_knowledge_index_requested"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admin_queues_indexed_knowledge_for_projection_removal() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-ai-removal-test-secret")
        async with factory() as setup_session:
            admin = User(phone="13600000020")
            source = OfficialKnowledgeSource(
                source_type="rule",
                title="Indexed rule",
                body_text="Public source already indexed.",
                city_code="330100",
                status="indexed",
            )
            setup_session.add_all([admin, source])
            await setup_session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        try:
            with TestClient(app) as client:
                response = client.patch(
                    f"/api/v1/admin/ai/knowledge-sources/{source.id}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "inactive", "reason": "Retire this public source."},
                )
                assert response.status_code == 200
                assert response.json()["status"] == "removing"
            async with factory() as verify_session:
                stored = await verify_session.get(OfficialKnowledgeSource, source.id)
                event = await verify_session.scalar(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == source.id)
                )
                assert stored is not None and stored.status == "removing"
                assert event is not None
                assert event.event_type == "ai.official_knowledge_removal_requested"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admin_can_queue_poi_knowledge_import() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-poi-import-test-secret")
        async with factory() as setup_session:
            admin = User(phone="13600000022")
            setup_session.add(admin)
            await setup_session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/admin/ai/poi-import-jobs",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"city_code": "330100", "keywords": ["West Lake", "West Lake", "museum"]},
                )
                assert response.status_code == 201
                job_id = response.json()["id"]
                assert response.json()["keywords"] == ["West Lake", "museum"]
            async with factory() as verify_session:
                job = await verify_session.get(PoiKnowledgeImportJob, job_id)
                event = await verify_session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id))
                assert job is not None and job.status == "queued"
                assert event is not None and event.event_type == "ai.poi_knowledge_import_requested"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admin_can_queue_structured_knowledge_import() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-structured-import-test-secret")
        async with factory() as setup_session:
            admin = User(phone="13600000023")
            setup_session.add(admin)
            await setup_session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/admin/ai/structured-knowledge-import-jobs",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "city_code": "330100",
                        "entries": [
                            {"source_type": "rule", "title": "West Lake walking", "body_text": "Leave time between lakeside stops."},
                            {"source_type": "template", "title": "One day lakeside", "body_text": "Start near the lake in the morning."},
                        ],
                    },
                )
                assert response.status_code == 201
                job_id = response.json()["id"]
                assert len(response.json()["entries"]) == 2
            async with factory() as verify_session:
                job = await verify_session.get(StructuredKnowledgeImportJob, job_id)
                event = await verify_session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id))
                assert job is not None and job.status == "queued"
                assert event is not None and event.event_type == "ai.structured_knowledge_import_requested"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admin_ai_metrics_are_deidentified_aggregate_counts() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-ai-metrics-test-secret")
        async with factory() as setup_session:
            admin = User(phone="13600000025")
            setup_session.add(admin)
            await setup_session.flush()
            setup_session.add_all([
                GenerationJob(user_id=admin.id, idempotency_key="metrics-failed", city_code="330100", prompt="Private prompt", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7), request_json={}, status="failed"),
                GenerationJob(user_id=admin.id, idempotency_key="metrics-preview", city_code="330100", prompt="Another private prompt", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7), request_json={}, status="awaiting_confirmation"),
                OfficialKnowledgeSource(source_type="rule", title="Indexed", body_text="Public", city_code="330100", status="indexed"),
                OfficialKnowledgeSource(source_type="template", title="Failed", body_text="Public", city_code="330100", status="failed"),
                PoiKnowledgeImportJob(requested_by=admin.id, city_code="330100", keywords=["West Lake"], status="failed"),
                StructuredKnowledgeImportJob(requested_by=admin.id, city_code="330100", entries=[], status="failed"),
            ])
            await setup_session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        try:
            with TestClient(app) as client:
                response = client.get("/api/v1/admin/ai/metrics", headers={"Authorization": f"Bearer {token}"})
                assert response.status_code == 200
                assert response.json() == {
                    "generation": {"total": 2, "failed": 1, "awaiting_confirmation": 1},
                    "knowledge": {"indexed": 1, "failed": 1, "pending_review": 0, "indexing": 0},
                    "imports": {"poi_failed": 1, "structured_failed": 1},
                }
                assert "Private prompt" not in response.text
        finally:
            await engine.dispose()

    asyncio.run(scenario())
