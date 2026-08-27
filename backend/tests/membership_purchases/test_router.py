import asyncio
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.integrations.alipay.adapter import AlipayPrecreateRequest, AlipayPrecreateResponse, AlipayWapPaymentRequest, AlipayWapRedirect, TradeQueryResult, VerifiedAlipayCallback
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.membership_purchases.router import provide_alipay_adapter
from app.modules.memberships.models import MembershipPlan


class FakeAlipayAdapter:
    app_id = "router-membership-app"

    async def create_wap_redirect(self, request: AlipayWapPaymentRequest) -> AlipayWapRedirect:
        return AlipayWapRedirect(f"https://sandbox.example.test/{request.out_trade_no}")

    async def create_precreate(self, request: AlipayPrecreateRequest) -> AlipayPrecreateResponse:
        return AlipayPrecreateResponse(f"alipay://qr/{request.out_trade_no}", "10000")

    async def verify_callback(self, payload: dict[str, str]) -> VerifiedAlipayCallback | None:
        if payload.get("sign") != "valid":
            return None
        return VerifiedAlipayCallback(payload["out_trade_no"], payload["trade_no"], payload["trade_status"], Decimal(payload["total_amount"]))

    async def query_trade(self, out_trade_no: str) -> TradeQueryResult:
        return TradeQueryResult(out_trade_no, "router-query", "TRADE_SUCCESS", Decimal("19.90"), "10000")


@pytest.fixture
def membership_api() -> tuple[TestClient, async_sessionmaker[AsyncSession], AuthService, FakeAlipayAdapter]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    auth = AuthService(InMemoryTTLStore(), secret="membership-router-secret")
    adapter = FakeAlipayAdapter()
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    asyncio.run(_create_tables(engine))
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[provide_alipay_adapter] = lambda: adapter
    with TestClient(app) as client:
        yield client, sessions, auth, adapter
    asyncio.run(engine.dispose())


async def _create_tables(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _seed(sessions: async_sessionmaker[AsyncSession]) -> tuple[User, User, MembershipPlan]:
    async with sessions() as session:
        owner, other = User(phone="13900000011"), User(phone="13900000012")
        plan = MembershipPlan(code=f"router-{uuid.uuid4().hex[:8]}", name="AI planning", duration_days=30, entitlement_codes=["ai_planning"], status="published", price_amount=Decimal("19.90"), currency="CNY", generation_quota=10, assistant_quota=300, purchasable=True)
        session.add_all([owner, other, plan])
        await session.commit()
        return owner, other, plan


def _headers(auth: AuthService, user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.create_access_token(user_id=user_id, audience='consumer', roles=[])}"}


def test_checkout_callback_query_and_owner_list(membership_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService, FakeAlipayAdapter]) -> None:
    client, sessions, auth, adapter = membership_api
    owner, other, plan = asyncio.run(_seed(sessions))
    create_headers = {**_headers(auth, owner.id), "Idempotency-Key": "purchase-key"}
    first = client.post("/api/v1/membership-purchases", headers=create_headers, json={"membership_plan_id": plan.id})
    second = client.post("/api/v1/membership-purchases", headers=create_headers, json={"membership_plan_id": plan.id})
    client_amount = client.post("/api/v1/membership-purchases", headers={**_headers(auth, owner.id), "Idempotency-Key": "amount-key"}, json={"membership_plan_id": plan.id, "amount": "0.01"})
    assert first.status_code == second.status_code == 201
    assert client_amount.status_code == 422
    assert first.json()["id"] == second.json()["id"]
    purchase = first.json()
    assert "idempotency_key" not in purchase
    denied = client.post(f"/api/v1/membership-purchases/{purchase['id']}/payments", headers={**_headers(auth, other.id), "Idempotency-Key": "payment-key"}, json={"provider": "alipay_sandbox"})
    assert denied.status_code == 404
    payment = client.post(f"/api/v1/membership-purchases/{purchase['id']}/payments", headers={**_headers(auth, owner.id), "Idempotency-Key": "payment-key"}, json={"provider": "alipay_sandbox"})
    assert payment.status_code == 201
    callback = {"app_id": adapter.app_id, "out_trade_no": payment.json()["payment_no"], "trade_no": "router-trade", "trade_status": "TRADE_SUCCESS", "total_amount": "19.90", "sign": "valid"}
    assert client.post("/api/v1/membership-payments/alipay/callback", data=callback).text == "success"
    assert client.post("/api/v1/membership-payments/alipay/callback", data=callback).text == "success"
    mine = client.get("/api/v1/membership-purchases/mine", headers=_headers(auth, owner.id))
    assert mine.status_code == 200
    assert mine.json()["items"][0]["authorization_status"] == "authorized"
    assert client.post(f"/api/v1/membership-purchases/{purchase['id']}:query-payment", headers=_headers(auth, owner.id)).json()["payment_status"] == "paid"


def test_qr_payment_owner_endpoints_redact_query_and_callback(membership_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService, FakeAlipayAdapter]) -> None:
    client, sessions, auth, adapter = membership_api
    owner, other, plan = asyncio.run(_seed(sessions))
    purchase = client.post("/api/v1/membership-purchases", headers={**_headers(auth, owner.id), "Idempotency-Key": "qr-purchase"}, json={"membership_plan_id": plan.id}).json()
    denied = client.post(f"/api/v1/membership-purchases/{purchase['id']}/qr-payments", headers=_headers(auth, other.id))
    assert denied.status_code == 404
    created = client.post(f"/api/v1/membership-purchases/{purchase['id']}/qr-payments", headers=_headers(auth, owner.id))
    assert created.status_code == 201
    assert created.json()["qr_code"].startswith("alipay://qr/")
    repeated = client.post(f"/api/v1/membership-purchases/{purchase['id']}/qr-payments", headers=_headers(auth, owner.id))
    assert repeated.json()["attempt_id"] == created.json()["attempt_id"]
    assert client.post(f"/api/v1/membership-purchases/{purchase['id']}/qr-payments:refresh", headers=_headers(auth, owner.id)).status_code == 409
    queried = client.post(f"/api/v1/membership-purchases/{purchase['id']}:query-payment", headers=_headers(auth, owner.id))
    assert queried.status_code == 200
    assert queried.json()["qr_code"] is None
    callback = {"app_id": adapter.app_id, "out_trade_no": created.json()["payment_no"], "trade_no": "router-query", "trade_status": "TRADE_SUCCESS", "total_amount": "19.90", "sign": "valid"}
    assert client.post("/api/v1/membership-payments/alipay/callback", data=callback).text == "success"
    assert client.post("/api/v1/membership-payments/alipay/callback", data=callback).text == "success"
    mine = client.get("/api/v1/membership-purchases/mine", headers=_headers(auth, owner.id)).json()
    assert "qr_code" not in mine["items"][0]
