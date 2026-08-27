import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.providers.models import Experience, ExperienceSession, Provider


def test_public_experience_catalog_exposes_only_published_approved_experiences() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with session_factory() as session:
            approved_owner = User(phone="13600000101")
            other_owner = User(phone="13600000102")
            hidden_owner = User(phone="13600000103")
            session.add_all((approved_owner, other_owner, hidden_owner))
            await session.flush()
            approved = Provider(
                applicant_id=approved_owner.id,
                provider_type="guide",
                legal_name="West Lake Walks",
                contact="private-provider-contact@example.test",
                qualification_asset_ids=["asset-1"],
                status="approved",
            )
            other = Provider(
                applicant_id=other_owner.id,
                provider_type="guide",
                legal_name="Canal Tours",
                contact="private-other-contact@example.test",
                qualification_asset_ids=["asset-2"],
                status="approved",
            )
            rejected = Provider(
                applicant_id=hidden_owner.id,
                provider_type="guide",
                legal_name="Hidden Tours",
                contact="private-hidden-contact@example.test",
                qualification_asset_ids=["asset-3"],
                status="rejected",
            )
            session.add_all((approved, other, rejected))
            await session.flush()
            published = Experience(
                provider_id=approved.id,
                title="Sunset walk",
                description="A guided lakeside walk.",
                poi_id="B001",
                poi_name="West Lake",
                poi_address="Hangzhou, Zhejiang",
                price_amount=Decimal("120.00"),
                currency="CNY",
                cancellation_policy="Cancel at least 24 hours before departure.",
                status="published",
            )
            other_published = Experience(
                provider_id=other.id,
                title="Canal cruise",
                description="A canal cruise.",
                poi_id="B002",
                poi_name="Grand Canal",
                poi_address="Hangzhou, Zhejiang",
                price_amount=Decimal("180.00"),
                currency="CNY",
                cancellation_policy="No refunds after confirmation.",
                status="published",
            )
            draft = Experience(
                provider_id=approved.id,
                title="Private draft",
                description="Not public.",
                poi_id="B003",
                poi_name="Draft POI",
                poi_address="Private address",
                price_amount=Decimal("1.00"),
                currency="CNY",
                cancellation_policy="Private.",
                status="draft",
            )
            rejected_provider_experience = Experience(
                provider_id=rejected.id,
                title="Rejected provider experience",
                description="Not public.",
                poi_id="B004",
                poi_name="Hidden POI",
                poi_address="Private address",
                price_amount=Decimal("1.00"),
                currency="CNY",
                cancellation_policy="Private.",
                status="published",
            )
            session.add_all((published, other_published, draft, rejected_provider_experience))
            await session.flush()
            now = datetime.now(UTC)
            upcoming = ExperienceSession(
                experience_id=published.id,
                starts_at=now + timedelta(days=1),
                capacity=10,
                reserved_count=3,
                price_amount=Decimal("140.00"),
                currency="CNY",
                status="scheduled",
            )
            inherited_price = ExperienceSession(
                experience_id=published.id,
                starts_at=now + timedelta(days=2),
                capacity=6,
                reserved_count=0,
                price_amount=None,
                currency=None,
                status="scheduled",
            )
            past = ExperienceSession(
                experience_id=published.id,
                starts_at=now - timedelta(minutes=1),
                capacity=8,
                reserved_count=0,
                price_amount=None,
                currency=None,
                status="scheduled",
            )
            cancelled = ExperienceSession(
                experience_id=published.id,
                starts_at=now + timedelta(days=3),
                capacity=8,
                reserved_count=0,
                price_amount=None,
                currency=None,
                status="cancelled",
            )
            session.add_all((upcoming, inherited_price, past, cancelled))
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        try:
            with TestClient(app) as client:
                listed = client.get("/api/v1/experiences")
                assert listed.status_code == 200
                assert {item["id"] for item in listed.json()["items"]} == {published.id, other_published.id}
                first = next(item for item in listed.json()["items"] if item["id"] == published.id)
                assert first == {
                    "id": published.id,
                    "title": "Sunset walk",
                    "poi": {"id": "B001", "name": "West Lake", "address": "Hangzhou, Zhejiang"},
                    "provider": {"id": approved.id, "name": "West Lake Walks"},
                    "price_amount": "120.00",
                    "currency": "CNY",
                    "status": "published",
                }
                assert "private-provider-contact@example.test" not in str(listed.json())

                filtered = client.get("/api/v1/experiences", params={"provider_id": approved.id, "limit": 1})
                assert filtered.status_code == 200
                assert [item["id"] for item in filtered.json()["items"]] == [published.id]
                assert client.get("/api/v1/experiences", params={"limit": 101}).status_code == 422

                detail = client.get(f"/api/v1/experiences/{published.id}")
                assert detail.status_code == 200
                body = detail.json()
                assert body["description"] == "A guided lakeside walk."
                assert body["cancellation_policy"] == "Cancel at least 24 hours before departure."
                assert body["poi"] == {"id": "B001", "name": "West Lake", "address": "Hangzhou, Zhejiang"}
                assert body["provider"] == {"id": approved.id, "name": "West Lake Walks"}
                assert {session["id"] for session in body["sessions"]} == {upcoming.id, inherited_price.id}
                rendered_sessions = {session["id"]: session for session in body["sessions"]}
                assert rendered_sessions[upcoming.id]["remaining_capacity"] == 7
                assert rendered_sessions[upcoming.id]["price_amount"] == "140.00"
                assert rendered_sessions[upcoming.id]["status"] == "scheduled"
                assert rendered_sessions[inherited_price.id]["price_amount"] == "120.00"
                assert rendered_sessions[inherited_price.id]["currency"] == "CNY"
                assert "private-provider-contact@example.test" not in str(body)

                assert client.get(f"/api/v1/experiences/{draft.id}").status_code == 404
                assert client.get(f"/api/v1/experiences/{rejected_provider_experience.id}").status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(scenario())
