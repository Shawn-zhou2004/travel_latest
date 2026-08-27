import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User, UserRole
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.providers.models import Experience, ExperienceBooking, ExperienceSession, Provider


def test_provider_workspace_requires_scoped_backoffice_access_and_manages_future_sessions() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="provider-workspace-router-test-secret")
        async with factory() as session:
            owner, other_owner, platform_admin = (
                User(phone=phone) for phone in ("13600000201", "13600000202", "13600000203")
            )
            session.add_all((owner, other_owner, platform_admin))
            await session.flush()
            provider = Provider(
                applicant_id=owner.id,
                provider_type="guide",
                legal_name="Lake Tours",
                contact="owner@example.test",
                qualification_asset_ids=["asset-1"],
                status="approved",
            )
            other_provider = Provider(
                applicant_id=other_owner.id,
                provider_type="guide",
                legal_name="Canal Tours",
                contact="other@example.test",
                qualification_asset_ids=["asset-2"],
                status="approved",
            )
            session.add_all((provider, other_provider))
            await session.flush()
            experience = Experience(
                provider_id=provider.id,
                title="Sunset walk",
                description="A guided lakeside walk.",
                poi_id="B001",
                poi_name="West Lake",
                poi_address="Hangzhou",
                price_amount=Decimal("120.00"),
                currency="CNY",
                cancellation_policy="Cancel 24 hours ahead.",
                status="draft",
            )
            other_experience = Experience(
                provider_id=other_provider.id,
                title="Canal cruise",
                description="A canal cruise.",
                poi_id="B002",
                poi_name="Grand Canal",
                poi_address="Hangzhou",
                price_amount=Decimal("180.00"),
                currency="CNY",
                cancellation_policy="No refunds.",
                status="published",
            )
            session.add_all((experience, other_experience))
            await session.flush()
            future_session = ExperienceSession(
                experience_id=experience.id,
                starts_at=datetime.now(UTC) + timedelta(days=1),
                capacity=8,
                reserved_count=3,
                price_amount=None,
                currency=None,
                status="scheduled",
            )
            past_session = ExperienceSession(
                experience_id=experience.id,
                starts_at=datetime.now(UTC) - timedelta(days=1),
                capacity=8,
                reserved_count=0,
                price_amount=None,
                currency=None,
                status="completed",
            )
            session.add_all((future_session, past_session))
            await session.flush()
            booking = ExperienceBooking(
                experience_session_id=future_session.id,
                user_id=owner.id,
                traveler_count=1,
                verification_code="verify-code-1",
            )
            session.add(booking)
            session.add_all(
                (
                    UserRole(user_id=owner.id, role="provider_admin", scope_key=provider.id),
                    UserRole(user_id=other_owner.id, role="provider_staff", scope_key=other_provider.id),
                    UserRole(user_id=platform_admin.id, role="platform_admin", scope_key=""),
                )
            )
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        owner_headers = {
            "Authorization": f"Bearer {auth.create_access_token(user_id=owner.id, audience='admin', roles=['provider_admin'])}"
        }
        other_headers = {
            "Authorization": f"Bearer {auth.create_access_token(user_id=other_owner.id, audience='admin', roles=['provider_staff'])}"
        }
        platform_headers = {
            "Authorization": f"Bearer {auth.create_access_token(user_id=platform_admin.id, audience='admin', roles=['platform_admin'])}"
        }
        try:
            with TestClient(app) as client:
                listed = client.get("/api/v1/provider/experiences", params={"provider_id": provider.id}, headers=owner_headers)
                assert listed.status_code == 200
                assert listed.json()["items"][0]["poi"] == {"id": "B001", "name": "West Lake", "address": "Hangzhou"}

                assert client.get(
                    "/api/v1/provider/experiences", params={"provider_id": other_provider.id}, headers=owner_headers
                ).status_code == 404
                assert client.get(f"/api/v1/provider/experiences/{experience.id}", headers=other_headers).status_code == 404
                assert client.get(f"/api/v1/provider/experiences/{experience.id}", headers=platform_headers).status_code == 403
                assert client.get(f"/api/v1/provider/experiences/{experience.id}").status_code == 401

                immutable_poi = client.patch(
                    f"/api/v1/provider/experiences/{experience.id}",
                    headers=owner_headers,
                    json={"poi_id": "B003"},
                )
                assert immutable_poi.status_code == 422

                updated = client.patch(
                    f"/api/v1/provider/experiences/{experience.id}",
                    headers=owner_headers,
                    json={"title": "Sunrise walk", "status": "published"},
                )
                assert updated.status_code == 200
                assert updated.json()["title"] == "Sunrise walk"
                assert updated.json()["status"] == "published"

                sessions = client.get(f"/api/v1/provider/experiences/{experience.id}/sessions", headers=owner_headers)
                assert sessions.status_code == 200
                assert {item["id"] for item in sessions.json()["items"]} == {future_session.id, past_session.id}

                bookings = client.get(
                    "/api/v1/provider/experience-bookings",
                    params={"provider_id": provider.id, "status": "reserved"},
                    headers=owner_headers,
                )
                assert bookings.status_code == 200
                assert bookings.json()["items"] == [
                    {
                        "id": booking.id,
                        "experience_title": "Sunrise walk",
                        "starts_at": bookings.json()["items"][0]["starts_at"],
                        "traveler_count": 1,
                        "status": "reserved",
                        "verified_at": None,
                    }
                ]
                assert bookings.json()["items"][0]["starts_at"].removesuffix("+00:00") == future_session.starts_at.isoformat().removesuffix("+00:00")
                assert client.get(
                    "/api/v1/provider/experience-bookings",
                    params={"provider_id": other_provider.id},
                    headers=owner_headers,
                ).status_code == 404

                below_reserved = client.patch(
                    f"/api/v1/provider/experiences/{experience.id}/sessions/{future_session.id}",
                    headers=owner_headers,
                    json={"capacity": 2},
                )
                assert below_reserved.status_code == 422

                changed_session = client.patch(
                    f"/api/v1/provider/experiences/{experience.id}/sessions/{future_session.id}",
                    headers=owner_headers,
                    json={"capacity": 10, "price_amount": "130.00", "currency": "CNY"},
                )
                assert changed_session.status_code == 200
                assert changed_session.json()["remaining_capacity"] == 7

                assert client.patch(
                    f"/api/v1/provider/experiences/{experience.id}/sessions/{past_session.id}",
                    headers=owner_headers,
                    json={"status": "cancelled"},
                ).status_code == 422

                assert client.post(
                    f"/api/v1/provider/experience-bookings/{booking.id}:verify",
                    params={"provider_id": other_provider.id},
                    headers=owner_headers,
                    json={"verification_code": booking.verification_code},
                ).status_code == 404
                assert client.post(
                    f"/api/v1/provider/experience-bookings/{booking.id}:verify",
                    params={"provider_id": provider.id},
                    headers=other_headers,
                    json={"verification_code": booking.verification_code},
                ).status_code == 404
                assert client.post(
                    f"/api/v1/provider/experience-bookings/{booking.id}:verify",
                    params={"provider_id": provider.id},
                    headers=platform_headers,
                    json={"verification_code": booking.verification_code},
                ).status_code == 403
                verified = client.post(
                    f"/api/v1/provider/experience-bookings/{booking.id}:verify",
                    params={"provider_id": provider.id},
                    headers=owner_headers,
                    json={"verification_code": booking.verification_code},
                )
                assert verified.status_code == 200
                assert verified.json()["status"] == "verified"
        finally:
            await engine.dispose()

    asyncio.run(scenario())
