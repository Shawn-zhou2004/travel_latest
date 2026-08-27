import asyncio
from collections.abc import AsyncIterator
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.community.models import CompanionRequest


def test_admin_companion_queue_exposes_plan_metadata_not_private_route_or_chat() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="companion-admin-test")
        async with sessions() as session:
            admin, owner = User(phone="13700000015"), User(phone="13700000016")
            session.add_all([admin, owner])
            await session.flush()
            session.add(CompanionRequest(owner_id=owner.id, title="Hangzhou walk", description="legacy", city_code="330100", trip_kind="trip", start_date=date(2026, 10, 1), end_date=date(2026, 10, 2), party_size=3, accepted_count=1, travel_pace="slow", interest_tags=["citywalk"], intro_text="Public intro", review_status="pending_review", status="open"))
            await session.commit()
        app = create_app()
        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        try:
            with TestClient(app) as client:
                response = client.get("/api/v1/admin/companion-requests?status=pending_review", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            item = response.json()["items"][0]
            assert item == {
                "id": item["id"], "owner_id": owner.id, "title": "Hangzhou walk", "destination": "330100",
                "trip_kind": "trip", "has_itinerary": False, "start_date": "2026-10-01", "end_date": "2026-10-02",
                "party_size": 3, "accepted_count": 1, "travel_pace": "slow", "interest_tags": ["citywalk"],
                "intro_text": "Public intro", "description": "legacy", "business_status": "open",
                "status": "pending_review", "review_reason": None, "created_at": item["created_at"],
            }
            assert {"itinerary_snapshot", "protected_itinerary", "conversation_id", "phone", "members", "applications"}.isdisjoint(item)
        finally:
            await engine.dispose()
    asyncio.run(scenario())
