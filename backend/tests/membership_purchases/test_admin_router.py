import asyncio
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.membership_purchases.models import MembershipPurchase
from app.modules.memberships.models import MembershipPlan


@pytest.fixture
def admin_api() -> tuple[TestClient, async_sessionmaker[AsyncSession], AuthService]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    auth = AuthService(InMemoryTTLStore(), secret="membership-admin-router-secret")
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    asyncio.run(_create_tables(engine))
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_auth_service] = lambda: auth
    with TestClient(app) as client:
        yield client, sessions, auth
    asyncio.run(engine.dispose())


async def _create_tables(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _seed(sessions: async_sessionmaker[AsyncSession]) -> tuple[User, MembershipPlan, MembershipPurchase]:
    async with sessions() as session:
        user = User(phone="13900000021")
        plan = MembershipPlan(code=f"admin-{uuid.uuid4().hex[:8]}", name="AI planning", duration_days=30, entitlement_codes=["ai_planning"], status="published", price_amount=Decimal("19.90"), currency="CNY", generation_quota=10, assistant_quota=300, purchasable=True)
        session.add_all([user, plan])
        await session.flush()
        purchase = MembershipPurchase(user_id=user.id, membership_plan_id=plan.id, plan_name_snapshot=plan.name, amount=Decimal("19.90"), currency="CNY", duration_days=30, generation_quota=10, assistant_quota=300, idempotency_key="admin-purchase", status="paid", payment_status="paid")
        session.add(purchase)
        await session.commit()
        return user, plan, purchase


def _headers(auth: AuthService) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.create_access_token(user_id=str(uuid.uuid4()), audience='admin', roles=['platform_admin'])}"}


def test_admin_plan_configuration_validates_sale_state(admin_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService]) -> None:
    client, sessions, auth = admin_api
    _, plan, _ = asyncio.run(_seed(sessions))
    body = {"code": "ai-annual", "name": "AI 年卡", "duration_days": 365, "entitlement_codes": ["ai_planning"], "price_amount": "199.00", "currency": "CNY", "generation_quota": 100, "assistant_quota": 3000, "purchasable": False}
    created = client.post("/api/v1/admin/membership-plans", headers=_headers(auth), json=body)
    assert created.status_code == 201
    assert created.json()["price_amount"] == "199.00"
    assert client.patch(f"/api/v1/admin/membership-plans/{created.json()['id']}", headers=_headers(auth), json={"purchasable": True}).status_code == 409
    updated = client.patch(f"/api/v1/admin/membership-plans/{plan.id}", headers=_headers(auth), json={"price_amount": "29.90", "generation_quota": 12, "assistant_quota": 360, "purchasable": True})
    assert updated.status_code == 200
    assert updated.json()["purchasable"] is True
    archived = client.post(f"/api/v1/admin/membership-plans/{plan.id}:archive", headers=_headers(auth))
    assert archived.status_code == 200
    assert archived.json()["purchasable"] is False


def test_admin_purchase_audit_is_redacted_and_retry_requires_paid_pending(admin_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService]) -> None:
    client, sessions, auth = admin_api
    _, _, purchase = asyncio.run(_seed(sessions))
    response = client.get("/api/v1/admin/membership-purchases?status=paid", headers=_headers(auth))
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == purchase.id
    assert "payment_no" not in item
    assert "provider_transaction_id" not in item
    assert "raw_payload" not in item
    retried = client.post(f"/api/v1/admin/membership-purchases/{purchase.id}:retry-authorization", headers=_headers(auth))
    assert retried.status_code == 200
    assert retried.json()["authorization_status"] == "authorized"
    assert client.post(f"/api/v1/admin/membership-purchases/{purchase.id}:retry-authorization", headers=_headers(auth)).status_code == 409
