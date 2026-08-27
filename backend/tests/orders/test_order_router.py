import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.integrations.alipay.adapter import AlipayWapPaymentRequest, AlipayWapRedirect, TradeQueryResult, UnavailableAlipayAdapter, VerifiedAlipayCallback
from app.main import create_app
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.orders.models import PaymentCallbackEvent, PaymentRecord, TravelOffer, TravelOrder, TravelSearchJob
from app.modules.orders.router import provide_alipay_adapter


class FakeAlipayAdapter:
    app_id = "sandbox-app-id"

    def __init__(self, query_status: str = "WAIT_BUYER_PAY") -> None:
        self.query_status = query_status
        self.created: list[str] = []
        self.queried: list[str] = []

    async def create_wap_redirect(self, request: AlipayWapPaymentRequest) -> AlipayWapRedirect:
        assert request.total_amount == Decimal("188.00")
        self.created.append(request.out_trade_no)
        return AlipayWapRedirect(f"https://sandbox.example.test/checkout/{request.out_trade_no}")

    async def verify_callback(self, payload: dict[str, str]) -> VerifiedAlipayCallback | None:
        if payload.get("sign") != "valid-signature":
            return None
        return VerifiedAlipayCallback(payload["out_trade_no"], payload["trade_no"], payload["trade_status"], Decimal(payload["total_amount"]))

    async def query_trade(self, out_trade_no: str) -> TradeQueryResult:
        self.queried.append(out_trade_no)
        return TradeQueryResult(out_trade_no, "query-trade-no", self.query_status, Decimal("188.00"), "10000")


@pytest.fixture
def order_api() -> tuple[TestClient, async_sessionmaker[AsyncSession], AuthService, FakeAlipayAdapter]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    auth_service = AuthService(InMemoryTTLStore(), secret="order-router-test-secret")
    adapter = FakeAlipayAdapter()
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    asyncio.run(_create_tables(engine))
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[provide_alipay_adapter] = lambda: adapter
    with TestClient(app) as client:
        yield client, session_factory, auth_service, adapter
    asyncio.run(engine.dispose())


async def _create_tables(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _create_order(session_factory: async_sessionmaker[AsyncSession]) -> tuple[TravelOrder, User, User]:
    async with session_factory() as session:
        owner, other = User(phone="13600000031"), User(phone="13600000032")
        session.add_all([owner, other])
        await session.flush()
        job = TravelSearchJob(user_id=owner.id, idempotency_key="router-search", search_type="hotel", query_snapshot={}, status="completed", source="test")
        session.add(job)
        await session.flush()
        offer = TravelOffer(search_job_id=job.id, source="test", external_offer_id="router-offer", title="Room", amount=Decimal("188.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={})
        session.add(offer)
        await session.flush()
        order = TravelOrder(user_id=owner.id, offer_id=offer.id, idempotency_key="router-order", amount=Decimal("188.00"), currency="CNY", offer_snapshot={})
        session.add(order)
        await session.commit()
        return order, owner, other


def _headers(auth_service: AuthService, user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_service.create_access_token(user_id=user_id, audience='consumer', roles=[])}"}


def test_checkout_is_owner_only_and_idempotent(order_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService, FakeAlipayAdapter]) -> None:
    client, _sessions, auth, adapter = order_api
    order, owner, other = asyncio.run(_create_order(_sessions))
    assert client.post(f"/api/v1/travel-orders/{order.id}/payments", headers={**_headers(auth, other.id), "Idempotency-Key": "payment-key"}, json={"provider": "alipay_sandbox"}).status_code == 404

    headers = {**_headers(auth, owner.id), "Idempotency-Key": "payment-key"}
    first = client.post(f"/api/v1/travel-orders/{order.id}/payments", headers=headers, json={"provider": "alipay_sandbox"})
    second = client.post(f"/api/v1/travel-orders/{order.id}/payments", headers=headers, json={"provider": "alipay_sandbox"})
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert first.json().keys() == {"id", "payment_no", "amount", "currency", "status", "redirect_url"}
    assert len(set(adapter.created)) == 1
    competing = client.post(
        f"/api/v1/travel-orders/{order.id}/payments",
        headers={**_headers(auth, owner.id), "Idempotency-Key": "another-payment-key"},
        json={"provider": "alipay_sandbox"},
    )
    assert competing.status_code == 409
    assert competing.json()["code"] == "PAYMENT_IN_PROGRESS"


def test_unconfigured_checkout_does_not_mutate(order_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService, FakeAlipayAdapter]) -> None:
    client, sessions, auth, _adapter = order_api
    client.app.dependency_overrides[provide_alipay_adapter] = UnavailableAlipayAdapter
    order, owner, _other = asyncio.run(_create_order(sessions))
    response = client.post(f"/api/v1/travel-orders/{order.id}/payments", headers={**_headers(auth, owner.id), "Idempotency-Key": "payment-key"}, json={"provider": "alipay_sandbox"})
    assert response.status_code == 503

    async def assert_no_change() -> None:
        async with sessions() as session:
            persisted = await session.get(TravelOrder, order.id)
            assert persisted is not None and persisted.status == "PENDING_CONFIRMATION"
            assert not list((await session.scalars(select(PaymentRecord))).all())

    asyncio.run(assert_no_change())


def test_callback_settles_once_without_duplicate_outbox(order_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService, FakeAlipayAdapter]) -> None:
    client, sessions, auth, adapter = order_api
    order, owner, _other = asyncio.run(_create_order(sessions))
    payment = client.post(f"/api/v1/travel-orders/{order.id}/payments", headers={**_headers(auth, owner.id), "Idempotency-Key": "payment-key"}, json={"provider": "alipay_sandbox"}).json()
    callback = {"app_id": adapter.app_id, "out_trade_no": payment["payment_no"], "trade_no": "callback-trade-no", "trade_status": "TRADE_SUCCESS", "total_amount": "188.00", "currency": "CNY", "sign": "valid-signature"}
    assert client.post("/api/v1/payments/alipay/callback", data=callback).text == "success"
    assert client.post("/api/v1/payments/alipay/callback", data=callback).text == "success"

    async def assert_settled_once() -> None:
        async with sessions() as session:
            assert len(list((await session.scalars(select(PaymentCallbackEvent))).all())) == 1
            assert len(list((await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "payment_record.paid"))).all())) == 1

    asyncio.run(assert_settled_once())


def test_query_settles_an_unresolved_payment(order_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService, FakeAlipayAdapter]) -> None:
    client, sessions, auth, adapter = order_api
    adapter.query_status = "TRADE_SUCCESS"
    order, owner, _other = asyncio.run(_create_order(sessions))
    payment = client.post(f"/api/v1/travel-orders/{order.id}/payments", headers={**_headers(auth, owner.id), "Idempotency-Key": "query-payment-key"}, json={"provider": "alipay_sandbox"}).json()

    response = client.post(f"/api/v1/travel-orders/{order.id}:query-payment", headers=_headers(auth, owner.id))

    assert response.status_code == 200
    assert response.json()["payment_status"] == "paid"
    assert adapter.queried == [payment["payment_no"]]
