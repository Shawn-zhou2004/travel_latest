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
from app.modules.admin.models import AdminAction, ExternalWebKnowledgeSource, WebKnowledgeCandidate, WebKnowledgeSearchJob
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_platform_admin_reviews_external_web_knowledge_sources_without_candidate_body_in_event() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="external-web-knowledge-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000104")
            session.add(admin)
            await session.flush()
            job = WebKnowledgeSearchJob(requested_by=admin.id, city_code="330100", query="West Lake", target_domain="official", status="succeeded")
            session.add(job)
            await session.flush()
            candidate = WebKnowledgeCandidate(job_id=job.id, title="Candidate title", excerpt="Raw candidate content must not be indexed directly.", source_url="https://example.gov/notice", source_host="example.gov", excerpt_hash="c" * 64, city_code="330100", target_domain="official", status="approved")
            session.add(candidate)
            await session.flush()
            source = ExternalWebKnowledgeSource(candidate_id=candidate.id, target_domain="official", title="Reviewed title", body_text="Administrator-edited source body.", city_code="330100", source_url=candidate.source_url, source_host=candidate.source_host, status="pending_review")
            session.add(source)
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['platform_admin'])}"}
        non_admin_headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['provider_admin'])}"}
        try:
            with TestClient(app) as client:
                assert client.get("/api/v1/admin/ai/external-web-knowledge-sources", headers=non_admin_headers).status_code == 403
                assert client.patch(f"/api/v1/admin/ai/external-web-knowledge-sources/{source.id}", headers=non_admin_headers, json={"status": "approved"}).status_code == 403
                listed = client.get("/api/v1/admin/ai/external-web-knowledge-sources?status=pending_review", headers=admin_headers)
                assert listed.status_code == 200
                assert listed.json()["items"][0]["id"] == source.id
                reviewed = client.patch(f"/api/v1/admin/ai/external-web-knowledge-sources/{source.id}", headers=admin_headers, json={"status": "approved"})
                assert reviewed.status_code == 200
                assert reviewed.json()["status"] == "indexing"
                assert client.patch(f"/api/v1/admin/ai/external-web-knowledge-sources/{source.id}", headers=admin_headers, json={"status": "approved"}).status_code == 409
            async with factory() as session:
                stored = await session.get(ExternalWebKnowledgeSource, source.id)
                event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == source.id))
                audit = await session.scalar(select(AdminAction).where(AdminAction.target_id == source.id))
                assert stored is not None and stored.status == "indexing" and stored.reviewed_by == admin.id
                assert event is not None
                assert event.event_type == "ai.external_web_knowledge_index_requested"
                assert dict(event.payload_json) == {"source_id": source.id}
                assert candidate.excerpt not in str(event.payload_json)
                assert audit is not None and audit.action == "ai_external_web_knowledge_source.indexing"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_external_web_knowledge_rejection_requires_reason_and_pending_status() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="external-web-knowledge-rejection-test-secret")
        async with factory() as session:
            admin = User(phone="13600000105")
            session.add(admin)
            await session.flush()
            job = WebKnowledgeSearchJob(requested_by=admin.id, city_code="330100", query="West Lake", target_domain="community")
            session.add(job)
            await session.flush()
            candidate = WebKnowledgeCandidate(job_id=job.id, title="Candidate", excerpt="Excerpt", source_url="https://example.com/advice", source_host="example.com", excerpt_hash="d" * 64, city_code="330100", target_domain="community", status="approved")
            session.add(candidate)
            await session.flush()
            source = ExternalWebKnowledgeSource(candidate_id=candidate.id, target_domain="community", title="Reviewed", body_text="Reviewed body.", city_code="330100", source_url=candidate.source_url, source_host=candidate.source_host, status="pending_review")
            session.add(source)
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['platform_admin'])}"}
        try:
            with TestClient(app) as client:
                assert client.patch(f"/api/v1/admin/ai/external-web-knowledge-sources/{source.id}", headers=headers, json={"status": "rejected", "reason": "   "}).status_code == 422
                rejected = client.patch(f"/api/v1/admin/ai/external-web-knowledge-sources/{source.id}", headers=headers, json={"status": "rejected", "reason": "Source lacks a verifiable author."})
                assert rejected.status_code == 200
                assert rejected.json()["status"] == "rejected"
                assert rejected.json()["review_reason"] == "Source lacks a verifiable author."
                assert client.patch(f"/api/v1/admin/ai/external-web-knowledge-sources/{source.id}", headers=headers, json={"status": "rejected", "reason": "Again."}).status_code == 409
            async with factory() as session:
                stored = await session.get(ExternalWebKnowledgeSource, source.id)
                events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == source.id))).all()
                assert stored is not None and stored.status == "rejected" and stored.reviewed_by == admin.id
                assert not events
        finally:
            await engine.dispose()

    asyncio.run(scenario())
