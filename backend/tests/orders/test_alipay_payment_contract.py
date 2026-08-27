import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.integrations.alipay.adapter import AlipayWapPaymentRequest, AlipayWapRedirect, TradeQueryResult, VerifiedAlipayCallback
from app.main import create_app
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.orders.models import PaymentCallbackEvent, TravelOffer, TravelOrder, TravelSearchJob
from app.modules.orders.router import provide_alipay_adapter


class FakeAlipayAdapter:
    app_id = "sandbox-app-id"

    async def create_wap_redirect(self, request: AlipayWapPaymentRequest) -> AlipayWapRedirect:
        return AlipayWapRedirect(f"https://sandbox.example.test/pay/{request.out_trade_no}")

    async def verify_callback(self, parameters: dict[str, str]) -> VerifiedAlipayCallback | None:
        if parameters.get("sign") != "valid":
            return None
        return VerifiedAlipayCallback(
            parameters["out_trade_no"], parameters["trade_no"], parameters["trade_status"], Decimal(parameters["total_amount"])
        )

    async def query_trade(self, out_trade_no: str) -> TradeQueryResult:
        return TradeQueryResult(out_trade_no, None, "WAIT_BUYER_PAY", None, "10000")


@pytest.fixture
def payment_api() -> tuple[TestClient, async_sessionmaker[AsyncSession], AuthService]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    auth_service = AuthService(InMemoryTTLStore(), secret="alipay-payment-contract-test-secret")
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    asyncio.run(_create_tables(engine))
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[provide_alipay_adapter] = FakeAlipayAdapter
    with TestClient(app) as client:
        yield client, session_factory, auth_service
    asyncio.run(engine.dispose())


async def _create_tables(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _create_order(session_factory: async_sessionmaker[AsyncSession]) -> tuple[TravelOrder, User, User]:
    async with session_factory() as session:
        owner, other = User(phone="13600000021"), User(phone="13600000022")
        session.add_all([owner, other])
        await session.flush()
        job = TravelSearchJob(user_id=owner.id, idempotency_key="alipay-search", search_type="hotel", query_snapshot={}, status="completed", source="test")
        session.add(job)
        await session.flush()
        offer = TravelOffer(search_job_id=job.id, source="test", external_offer_id="alipay-offer", title="Payment contract room", amount=Decimal("188.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={})
        session.add(offer)
        await session.flush()
        order = TravelOrder(user_id=owner.id, offer_id=offer.id, idempotency_key="alipay-order", amount=Decimal("188.00"), currency="CNY", offer_snapshot={})
        session.add(order)
        await session.commit()
        return order, owner, other


def _headers(auth_service: AuthService, user_id: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {auth_service.create_access_token(user_id=user_id, audience='consumer', roles=[])}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def test_checkout_requires_owner_key_and_alipay_provider(payment_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService]) -> None:
    client, sessions, auth = payment_api
    order, owner, other = asyncio.run(_create_order(sessions))
    url = f"/api/v1/travel-orders/{order.id}/payments"
    assert client.post(url, headers=_headers(auth, other.id, "key"), json={"provider": "alipay_sandbox"}).status_code == 404
    assert client.post(url, headers=_headers(auth, owner.id), json={"provider": "alipay_sandbox"}).status_code == 422
    assert client.post(url, headers=_headers(auth, owner.id, "key"), json={"provider": "other"}).status_code == 422


def test_checkout_is_idempotent_and_exposes_only_redirect_facts(payment_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService]) -> None:
    client, sessions, auth = payment_api
    order, owner, _ = asyncio.run(_create_order(sessions))
    url = f"/api/v1/travel-orders/{order.id}/payments"
    headers = _headers(auth, owner.id, "alipay-initiation-1")
    first = client.post(url, headers=headers, json={"provider": "alipay_sandbox"})
    second = client.post(url, headers=headers, json={"provider": "alipay_sandbox"})
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert first.json().keys() == {"id", "payment_no", "amount", "currency", "status", "redirect_url"}
    assert "sign" not in first.text.lower()


def test_callback_records_safe_facts_and_settles_once(payment_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService]) -> None:
    client, sessions, auth = payment_api
    order, owner, _ = asyncio.run(_create_order(sessions))
    payment = client.post(f"/api/v1/travel-orders/{order.id}/payments", headers=_headers(auth, owner.id, "payment-key"), json={"provider": "alipay_sandbox"}).json()
    callback = {"app_id": "sandbox-app-id", "out_trade_no": payment["payment_no"], "trade_no": "trade-1", "trade_status": "TRADE_SUCCESS", "total_amount": "188.00", "sign": "valid"}
    assert client.post("/api/v1/payments/alipay/callback", data=callback).text == "success"
    assert client.post("/api/v1/payments/alipay/callback", data=callback).text == "success"

    async def assert_effects() -> None:
        async with sessions() as session:
            event = await session.scalar(select(PaymentCallbackEvent))
            assert event is not None and event.raw_payload == {"out_trade_no": payment["payment_no"], "trade_no": "trade-1", "trade_status": "TRADE_SUCCESS", "total_amount": "188.00"}
            assert event.verification_status == "verified"
            assert event.processing_status == "processed"
            assert len(list((await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "payment_record.paid"))).all())) == 1

    asyncio.run(assert_effects())


def test_invalid_callback_cannot_block_later_verified_trade(payment_api: tuple[TestClient, async_sessionmaker[AsyncSession], AuthService]) -> None:
    client, sessions, auth = payment_api
    order, owner, _ = asyncio.run(_create_order(sessions))
    payment = client.post(f"/api/v1/travel-orders/{order.id}/payments", headers=_headers(auth, owner.id, "payment-key"), json={"provider": "alipay_sandbox"}).json()
    callback = {"app_id": "sandbox-app-id", "out_trade_no": payment["payment_no"], "trade_no": "trade-after-rejection", "trade_status": "TRADE_SUCCESS", "total_amount": "188.00"}
    assert client.post("/api/v1/payments/alipay/callback", data={**callback, "sign": "invalid"}).text == "failure"
    assert client.post("/api/v1/payments/alipay/callback", data={**callback, "sign": "valid"}).text == "success"

    async def assert_audit_does_not_reserve_trade_number() -> None:
        async with sessions() as session:
            events = list((await session.scalars(select(PaymentCallbackEvent))).all())
            assert len(events) == 2
            assert sum(event.provider_transaction_id == "trade-after-rejection" for event in events) == 1
            assert sum(event.verification_status == "rejected" for event in events) == 1

    asyncio.run(assert_audit_does_not_reserve_trade_number())
