from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.alipay import AlipayRefundRequest, TradeRefundResult
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.orders.models import PaymentRecord, RefundRecord, TravelOffer, TravelOrder, TravelSearchJob
from app.modules.orders.services import DomainError, RefundService


class FakeAlipay:
    async def refund_trade(self, request: AlipayRefundRequest) -> TradeRefundResult:
        return TradeRefundResult(request.out_trade_no, "trade-1", request.out_request_no, request.refund_amount, "Y", "10000")


async def _paid_order(session):
    user = User(phone=f"1{uuid.uuid4().int % 10**10:010d}")
    session.add(user)
    await session.flush()
    job = TravelSearchJob(user_id=user.id, idempotency_key="refund-search", search_type="hotel", query_snapshot={}, status="completed", source="test")
    session.add(job)
    await session.flush()
    offer = TravelOffer(search_job_id=job.id, source="test", external_offer_id="refund-offer", title="Room", amount=Decimal("12.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={})
    session.add(offer)
    await session.flush()
    order = TravelOrder(user_id=user.id, offer_id=offer.id, idempotency_key="refund-order", amount=offer.amount, currency="CNY", offer_snapshot={}, status="PAID_PENDING_FULFILLMENT", payment_status="paid", fulfillment_status="pending_confirmation")
    session.add(order)
    await session.flush()
    payment = PaymentRecord(order_id=order.id, idempotency_key="refund-payment", provider="alipay_sandbox", amount=order.amount, currency="CNY", status="paid")
    session.add(payment)
    await session.commit()
    return user, order, payment


@pytest.mark.anyio
async def test_full_refund_is_idempotent_and_settles_once() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        user, order, _ = await _paid_order(session)
        service = RefundService(session, FakeAlipay())
        refund = await service.create(order.id, user.id, "refund-key", Decimal("12.00"), "CNY", "Changed plans")
        assert refund.id == (await service.create(order.id, user.id, "refund-key", Decimal("12.00"), "CNY", "Changed plans")).id
        await service.process(refund.id)
        await session.refresh(order)
        assert (order.status, order.payment_status, order.fulfillment_status) == ("REFUNDED", "refunded", "not_supported")
        assert (await session.get(RefundRecord, refund.id)).status == "refunded"
        assert len(list((await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "refund_record.updated"))).all())) == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_refund_rejects_wrong_amount_and_other_owner() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        user, order, _ = await _paid_order(session)
        with pytest.raises(DomainError, match="full paid"):
            await RefundService(session, FakeAlipay()).create(order.id, user.id, "refund-key", Decimal("1.00"), "CNY", "Changed plans")
        with pytest.raises(DomainError, match="Order not found"):
            await RefundService(session, FakeAlipay()).create(order.id, str(uuid.uuid4()), "refund-key", Decimal("12.00"), "CNY", "Changed plans")
    await engine.dispose()
