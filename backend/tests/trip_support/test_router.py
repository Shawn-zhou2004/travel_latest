import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.models.user import User
from app.main import create_app
from app.models.base import Base
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_checklist_and_budget_routes_manage_trip_support() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth_service = AuthService(InMemoryTTLStore(), secret="trip-support-router-test-secret")
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth_service
        try:
            with TestClient(app) as client:
                phone = "13600000010"
                # SMS login requires an existing account; create it directly.
                async with session_factory() as seed:
                    seed.add(User(phone=phone))
                    await seed.commit()
                client.post("/api/v1/auth/sms-codes", json={"phone": phone})
                code = auth_service.store.get(f"auth:sms:{phone}")
                session = client.post("/api/v1/auth/sessions", json={"phone": phone, "code": code, "device_name": "trip-support-test"})
                token = session.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                itinerary = client.post("/api/v1/itineraries", headers=headers, json={
                    "title": "Trip support", "start_date": "2026-10-01", "end_date": "2026-10-01",
                }).json()

                checklist = client.post(f"/api/v1/itineraries/{itinerary['id']}/checklists", headers=headers, json={
                    "category": "行前", "content": "带好护照",
                })
                assert checklist.status_code == 201
                checklist_id = checklist.json()["id"]
                updated_checklist = client.patch(f"/api/v1/itineraries/{itinerary['id']}/checklists/{checklist_id}", headers=headers, json={"checked": True})
                assert updated_checklist.status_code == 200
                assert updated_checklist.json()["checked"] is True
                listed_checklist = client.get(f"/api/v1/itineraries/{itinerary['id']}/checklists", headers=headers)
                assert listed_checklist.json()["items"] == [updated_checklist.json()]

                budget = client.post(f"/api/v1/itineraries/{itinerary['id']}/budgets", headers=headers, json={
                    "category": "交通", "amount": "125.50", "currency": "cny", "description": "机场快线",
                })
                assert budget.status_code == 201
                budget_id = budget.json()["id"]
                updated_budget = client.patch(f"/api/v1/itineraries/{itinerary['id']}/budgets/{budget_id}", headers=headers, json={"amount": "150.00"})
                assert updated_budget.status_code == 200
                listed_budget = client.get(f"/api/v1/itineraries/{itinerary['id']}/budgets", headers=headers)
                assert listed_budget.status_code == 200
                assert listed_budget.json()["totals"] == [{"currency": "CNY", "total_amount": "150.00"}]

                invalid_currency = client.post(f"/api/v1/itineraries/{itinerary['id']}/budgets", headers=headers, json={
                    "category": "其他", "amount": "1", "currency": "ABC",
                })
                assert invalid_currency.status_code == 422

                assert client.delete(f"/api/v1/itineraries/{itinerary['id']}/checklists/{checklist_id}", headers=headers).status_code == 204
                assert client.delete(f"/api/v1/itineraries/{itinerary['id']}/budgets/{budget_id}", headers=headers).status_code == 204
        finally:
            await engine.dispose()

    asyncio.run(scenario())
