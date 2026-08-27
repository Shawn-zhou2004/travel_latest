import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.admin.models import OfficialKnowledgeSource, PoiCandidate
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_platform_admin_reviews_poi_candidate_and_creates_pending_knowledge_source() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="poi-candidate-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000061")
            session.add(admin)
            await session.flush()
            candidate = PoiCandidate(
                poi_id="B03830048T", name="天涯海角游览区", address="三亚市", city_code="460200",
                longitude=109.2, latitude=18.3, amap_type="风景名胜",
            )
            session.add(candidate)
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
                assert client.get("/api/v1/admin/ai/poi-candidates", headers=provider_headers).status_code == 403
                assert client.patch(f"/api/v1/admin/ai/poi-candidates/{candidate.id}", headers=admin_headers, json={"status": "approved", "tags": []}).status_code == 422
                approved = client.patch(
                    f"/api/v1/admin/ai/poi-candidates/{candidate.id}",
                    headers=admin_headers,
                    json={"status": "approved", "tags": ["经典必玩", "自然风光"], "admin_weight": 25},
                )
                assert approved.status_code == 200
                body = approved.json()
                assert body["status"] == "approved"
                assert body["tags"] == ["经典必玩", "自然风光"]
                assert body["official_knowledge_source_id"]
                assert client.patch(f"/api/v1/admin/ai/poi-candidates/{candidate.id}", headers=admin_headers, json={"status": "approved", "tags": ["经典必玩"]}).status_code == 409
            async with factory() as session:
                source = await session.get(OfficialKnowledgeSource, body["official_knowledge_source_id"])
                assert source is not None and source.status == "pending_review" and source.poi_id == candidate.poi_id
        finally:
            await engine.dispose()

    asyncio.run(scenario())
