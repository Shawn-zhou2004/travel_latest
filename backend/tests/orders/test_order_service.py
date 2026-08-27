import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.integrations.alipay.adapter import AlipayWapPaymentRequest, AlipayWapRedirect, TradeQueryResult, VerifiedAlipayCallback
from app.modules.orders.models import TravelOffer, TravelSearchJob
from app.modules.orders.services import DomainError, OrderService, PaymentService


class FakeAlipayAdapter:
    app_id = "sandbox-app-id"

    async def create_wap_redirect(self, request: AlipayWapPaymentRequest) -> AlipayWapRedirect:
        return AlipayWapRedirect(f"https://sandbox.example.test/checkout/{request.out_trade_no}")

    async def verify_callback(self, _: dict[str, str]) -> VerifiedAlipayCallback | None:
        return None

    async def query_trade(self, _: str) -> TradeQueryResult:
        return TradeQueryResult(None, None, "WAIT_BUYER_PAY", None, "10000")


def test_order_creation_is_idempotent_and_payment_requires_configuration() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(phone="13600000000")
            session.add(user)
            await session.flush()
            job = TravelSearchJob(user_id=user.id, idempotency_key="search-3", search_type="hotel", query_snapshot={}, status="completed", source="test")
            session.add(job)
            await session.flush()
            offer = TravelOffer(search_job_id=job.id, source="test", external_offer_id="o3", title="Room", amount=Decimal("188.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={"room": "standard"})
            session.add(offer)
            await session.commit()
            service = OrderService(session)
            first = await service.create_from_offer(user.id, offer.id, "order-key")
            second = await service.create_from_offer(user.id, offer.id, "order-key")
            assert first.id == second.id
            with pytest.raises(DomainError, match="not configured"):
                await PaymentService(session).create_checkout(first, "payment-key")
            payment, redirect_url = await PaymentService(session, FakeAlipayAdapter()).create_checkout(first, "payment-key")
            repeated, repeated_redirect_url = await PaymentService(session, FakeAlipayAdapter()).create_checkout(first, "payment-key")
            assert payment.amount == Decimal("188.00")
            assert payment.status == "paying"
            assert payment.id == repeated.id
            assert redirect_url == repeated_redirect_url
            assert first.status == "PAYING"
        await engine.dispose()
    asyncio.run(scenario())
