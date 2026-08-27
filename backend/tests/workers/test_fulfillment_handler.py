from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.events.consumer import consume_once
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.integrations.suppliers.client import SupplierFulfillmentConfirmationRequest, SupplierFulfillmentConfirmationResult
from app.modules.orders.models import PaymentRecord, TravelOffer, TravelOrder, TravelSearchJob
from app.workers import domain_handlers


class FakeSupplier:
    def __init__(self) -> None:
        self.calls = 0

    async def confirm_fulfillment(self, _request: SupplierFulfillmentConfirmationRequest) -> SupplierFulfillmentConfirmationResult:
        self.calls += 1
        return SupplierFulfillmentConfirmationResult(confirmed=True, code="CONFIRMED", message="confirmed", supplier_confirmation_id="confirm-1")


@pytest.mark.anyio
async def test_paid_event_fulfills_once_when_delivered_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        user_id = str(uuid.uuid4())
        session.add(User(id=user_id, phone=f"1{uuid.uuid4().int % 10**10:010d}"))
        job = TravelSearchJob(user_id=user_id, idempotency_key="worker-search", search_type="hotel", query_snapshot={}, status="completed", source="fake")
        session.add(job)
        await session.flush()
        offer = TravelOffer(search_job_id=job.id, source="fake", external_offer_id="offer-1", title="Room", amount=Decimal("12.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={})
        session.add(offer)
        await session.flush()
        order = TravelOrder(user_id=user_id, offer_id=offer.id, idempotency_key="worker-order", amount=Decimal("12.00"), currency="CNY", offer_snapshot={}, status="PAID_PENDING_FULFILLMENT", payment_status="paid", fulfillment_status="pending_confirmation")
        session.add(order)
        await session.flush()
        payment = PaymentRecord(order_id=order.id, idempotency_key="worker-payment", provider="alipay_sandbox", amount=order.amount, currency="CNY", status="paid")
        session.add(payment)
        await session.commit()

        supplier = FakeSupplier()
        monkeypatch.setattr(domain_handlers, "fulfillment_supplier", supplier)
        event = {"event_id": str(uuid.uuid4()), "event_type": "payment_record.paid", "payload": {"payment_id": payment.id}}
        assert await consume_once(session, "orders.fulfillment", event, domain_handlers._fulfill_paid_order, defer_idempotency=True)
        assert not await consume_once(session, "orders.fulfillment", event, domain_handlers._fulfill_paid_order, defer_idempotency=True)

        await session.refresh(order)
        assert order.fulfillment_status == "confirmed"
        assert supplier.calls == 1
        assert len(list((await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "travel_order.fulfillment_updated"))).all())) == 1
    await engine.dispose()
