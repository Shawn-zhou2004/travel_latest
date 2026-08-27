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


def test_platform_admin_creates_and_lists_websearch_jobs_with_job_id_only_outbox_payload() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="websearch-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000101")
            session.add(admin)
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
                denied = client.post("/api/v1/admin/ai/websearch-jobs", headers=non_admin_headers, json={"city_code": "330100", "query": "West Lake", "target_domain": "official"})
                assert denied.status_code == 403
                created = client.post("/api/v1/admin/ai/websearch-jobs", headers=admin_headers, json={"city_code": "330100", "query": " West Lake official notice ", "target_domain": "official"})
                assert created.status_code == 201
                job_id = created.json()["id"]
                assert created.json() | {"id": job_id, "created_at": created.json()["created_at"], "updated_at": created.json()["updated_at"]} == {"id": job_id, "requested_by": admin.id, "city_code": "330100", "query": "West Lake official notice", "target_domain": "official", "status": "queued", "provider_name": None, "error_code": None, "error_message": None, "result_count": 0, "created_at": created.json()["created_at"], "updated_at": created.json()["updated_at"]}
                listed = client.get("/api/v1/admin/ai/websearch-jobs?status=queued", headers=admin_headers)
                assert listed.status_code == 200
                assert [item["id"] for item in listed.json()["items"]] == [job_id]
            async with factory() as session:
                job = await session.get(WebKnowledgeSearchJob, job_id)
                event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id))
                assert job is not None and job.requested_by == admin.id
                assert event is not None
                assert event.event_type == "ai.web_knowledge_search_requested"
                assert dict(event.payload_json) == {"job_id": job_id}
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_platform_admin_approves_candidate_without_indexing_and_can_list_candidates() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="websearch-approval-test-secret")
        async with factory() as session:
            admin = User(phone="13600000102")
            session.add(admin)
            await session.flush()
            job = WebKnowledgeSearchJob(requested_by=admin.id, city_code="330100", query="West Lake", target_domain="community", status="succeeded", result_count=1)
            session.add(job)
            await session.flush()
            candidate = WebKnowledgeCandidate(job_id=job.id, title="Community advice", excerpt="Take the early bus.", source_url="https://example.com/advice", source_host="example.com", excerpt_hash="a" * 64, city_code="330100", target_domain="community")
            session.add(candidate)
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
                listed = client.get(f"/api/v1/admin/ai/websearch-jobs/{job.id}/candidates?status=needs_human_review", headers=headers)
                assert listed.status_code == 200
                assert listed.json()["items"][0]["id"] == candidate.id
                approved = client.patch(f"/api/v1/admin/ai/websearch-candidates/{candidate.id}", headers=headers, json={"status": "approved", "title": " Edited community advice ", "body_text": " Review this before publication. "})
                assert approved.status_code == 200
                assert approved.json()["status"] == "approved"
                source_id = approved.json()["external_web_source_id"]
                repeat = client.patch(f"/api/v1/admin/ai/websearch-candidates/{candidate.id}", headers=headers, json={"status": "approved", "title": "Again", "body_text": "Again"})
                assert repeat.status_code == 409
            async with factory() as session:
                stored_candidate = await session.get(WebKnowledgeCandidate, candidate.id)
                source = await session.get(ExternalWebKnowledgeSource, source_id)
                events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id.in_((candidate.id, source_id))))).all()
                audit = await session.scalar(select(AdminAction).where(AdminAction.target_id == candidate.id))
                assert stored_candidate is not None and stored_candidate.status == "approved"
                assert stored_candidate.reviewed_by == admin.id
                assert source is not None
                assert source.status == "pending_review"
                assert source.target_domain == "community"
                assert source.title == "Edited community advice"
                assert source.body_text == "Review this before publication."
                assert not events
                assert audit is not None and audit.action == "ai_websearch_candidate.approved"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_reject_requires_reason_and_only_pending_candidates_can_be_decided() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="websearch-rejection-test-secret")
        async with factory() as session:
            admin = User(phone="13600000103")
            session.add(admin)
            await session.flush()
            job = WebKnowledgeSearchJob(requested_by=admin.id, city_code="330100", query="West Lake", target_domain="official")
            session.add(job)
            await session.flush()
            candidate = WebKnowledgeCandidate(job_id=job.id, title="Unverified", excerpt="Check this.", source_url="https://example.gov/check", source_host="example.gov", excerpt_hash="b" * 64, city_code="330100", target_domain="official")
            session.add(candidate)
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
                missing_reason = client.patch(f"/api/v1/admin/ai/websearch-candidates/{candidate.id}", headers=headers, json={"status": "rejected", "reason": "   "})
                assert missing_reason.status_code == 422
                rejected = client.patch(f"/api/v1/admin/ai/websearch-candidates/{candidate.id}", headers=headers, json={"status": "rejected", "reason": "Source cannot be verified."})
                assert rejected.status_code == 200
                assert rejected.json()["status"] == "rejected"
                assert rejected.json()["review_reason"] == "Source cannot be verified."
                missing = client.get("/api/v1/admin/ai/websearch-jobs/not-a-real-job/candidates", headers=headers)
                assert missing.status_code == 404
            async with factory() as session:
                stored_candidate = await session.get(WebKnowledgeCandidate, candidate.id)
                source = await session.scalar(select(ExternalWebKnowledgeSource).where(ExternalWebKnowledgeSource.candidate_id == candidate.id))
                audit = await session.scalar(select(AdminAction).where(AdminAction.target_id == candidate.id))
                assert stored_candidate is not None and stored_candidate.status == "rejected"
                assert stored_candidate.reviewed_by == admin.id
                assert source is None
                assert audit is not None and audit.reason == "Source cannot be verified."
        finally:
            await engine.dispose()

    asyncio.run(scenario())
