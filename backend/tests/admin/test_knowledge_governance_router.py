import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import OfficialKnowledgeSource
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_approval_schedules_review_and_rejects_invalid_version_governance() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="official-governance-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000071")
            valid = OfficialKnowledgeSource(
                source_type="rule",
                title="Current rule",
                body_text="Reviewed official rule.",
                city_code="330100",
                status="pending_review",
                source_version="2.1",
            )
            invalid = OfficialKnowledgeSource(
                source_type="poi",
                title="Invalid version",
                body_text="This should remain pending.",
                city_code="330100",
                status="pending_review",
                source_version="invalid",
            )
            self_superseding = OfficialKnowledgeSource(
                source_type="template",
                title="Self superseding",
                body_text="This should remain pending.",
                city_code="330100",
                status="pending_review",
                source_version="2",
            )
            session.add_all([admin, valid, invalid, self_superseding])
            await session.flush()
            self_superseding.supersedes_document_id = self_superseding.id
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        try:
            with TestClient(app) as client:
                approved = client.patch(
                    f"/api/v1/admin/ai/knowledge-sources/{valid.id}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "indexed", "reason": "Current official rule approved."},
                )
                assert approved.status_code == 200
                rejected = client.patch(
                    f"/api/v1/admin/ai/knowledge-sources/{invalid.id}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "indexed", "reason": "Attempt invalid source."},
                )
                assert rejected.status_code == 409
                assert rejected.json()["code"] == "KNOWLEDGE_SOURCE_GOVERNANCE_INVALID"
                self_superseding_response = client.patch(
                    f"/api/v1/admin/ai/knowledge-sources/{self_superseding.id}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "indexed", "reason": "Attempt self-superseding source."},
                )
                assert self_superseding_response.status_code == 409
                assert self_superseding_response.json()["code"] == "KNOWLEDGE_SOURCE_GOVERNANCE_INVALID"

            async with factory() as session:
                stored_valid = await session.get(OfficialKnowledgeSource, valid.id)
                stored_invalid = await session.get(OfficialKnowledgeSource, invalid.id)
                events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == valid.id))).all()
                assert stored_valid is not None
                assert stored_valid.reviewed_at is not None
                assert stored_valid.next_review_at == stored_valid.reviewed_at + timedelta(days=180)
                assert stored_invalid is not None and stored_invalid.status == "pending_review"
                assert len(events) == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())
