from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.integrations.suppliers.client import SupplierFulfillmentConfirmationRequest, SupplierFulfillmentConfirmationResult
from app.modules.orders.models import PaymentRecord, TravelOffer, TravelOrder, TravelSearchJob
from app.modules.orders.services import (
    FulfillmentService,
    SupplierFulfillmentUnavailable,
)


class ConfirmingSupplier:
    def __init__(self, result: SupplierFulfillmentConfirmationResult) -> None:
        self.result = result
        self.requests: list[SupplierFulfillmentConfirmationRequest] = []

    async def confirm_fulfillment(self, request: SupplierFulfillmentConfirmationRequest) -> SupplierFulfillmentConfirmationResult:
        self.requests.append(request)
        return self.result


class UnavailableSupplier:
    async def confirm_fulfillment(self, _request: SupplierFulfillmentConfirmationRequest) -> SupplierFulfillmentConfirmationResult:
        return SupplierFulfillmentConfirmationResult(confirmed=False, code="SUPPLIER_UNAVAILABLE", message="temporary outage")


async def _paid_order(session: AsyncSession) -> tuple[TravelOrder, PaymentRecord]:
    user_id = str(uuid.uuid4())
    session.add(User(id=user_id, phone=f"1{uuid.uuid4().int % 10**10:010d}"))
    job = TravelSearchJob(user_id=user_id, idempotency_key="fulfillment-search", search_type="hotel", query_snapshot={}, status="completed", source="fake")
    session.add(job)
    await session.flush()
    offer = TravelOffer(
        search_job_id=job.id, source="fake", external_offer_id="offer-1", title="Room", amount=Decimal("12.00"), currency="CNY",
        availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={"source": "fake"},
    )
    session.add(offer)
    await session.flush()
    order = TravelOrder(
        user_id=user_id,
        offer_id=offer.id,
        idempotency_key="fulfillment-order",
        amount=Decimal("12.00"),
        currency="CNY",
        offer_snapshot={"source": "fake", "external_offer_id": "offer-1"},
        status="PAID_PENDING_FULFILLMENT",
        payment_status="paid",
        fulfillment_status="pending_confirmation",
    )
    session.add(order)
    await session.flush()
    payment = PaymentRecord(
        order_id=order.id,
        idempotency_key="fulfillment-payment",
        provider="alipay_sandbox",
        amount=order.amount,
        currency="CNY",
        status="paid",
    )
    session.add(payment)
    await session.commit()
    return order, payment


@pytest.mark.anyio
async def test_fulfillment_confirms_once_and_emits_safe_terminal_event() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        order, payment = await _paid_order(session)
        supplier = ConfirmingSupplier(SupplierFulfillmentConfirmationResult(confirmed=True, code="CONFIRMED", message="confirmed", supplier_confirmation_id="confirm-1"))
        service = FulfillmentService(session, supplier)
        attempt = await service.start_attempt(payment.id)
        assert attempt is not None
        await session.commit()
        await service.confirm(attempt)

        assert await service.start_attempt(payment.id) is None
        await session.refresh(order)
        assert (order.status, order.payment_status, order.fulfillment_status) == ("CONFIRMED", "paid", "confirmed")
        assert len(supplier.requests) == 1
        events = list((await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "travel_order.fulfillment_updated"))).all())
        assert len(events) == 1
        assert events[0].payload_json == {
            "travel_order_id": order.id,
            "user_id": order.user_id,
            "status": "CONFIRMED",
            "payment_status": "paid",
            "fulfillment_status": "confirmed",
            "failure_code": None,
        }
    await engine.dispose()


@pytest.mark.anyio
async def test_typed_terminal_failure_does_not_confirm_order() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        order, payment = await _paid_order(session)
        service = FulfillmentService(session, ConfirmingSupplier(SupplierFulfillmentConfirmationResult(confirmed=False, code="OFFER_SOLD_OUT", message="sold out")))
        attempt = await service.start_attempt(payment.id)
        assert attempt is not None
        await session.commit()
        await service.confirm(attempt)

        await session.refresh(order)
        assert (order.status, order.payment_status, order.fulfillment_status, order.failure_code) == ("FAILED", "failed", "failed", "OFFER_SOLD_OUT")
    await engine.dispose()


@pytest.mark.anyio
async def test_supplier_unavailable_releases_claim_for_retry() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        order, payment = await _paid_order(session)
        service = FulfillmentService(session, UnavailableSupplier())
        attempt = await service.start_attempt(payment.id)
        assert attempt is not None
        await session.commit()
        with pytest.raises(SupplierFulfillmentUnavailable):
            await service.confirm(attempt)
        await service.prepare_retry(order.id)

        await session.refresh(order)
        assert (order.status, order.payment_status, order.fulfillment_status, order.failure_code) == ("PAID_PENDING_FULFILLMENT", "paid", "pending_confirmation", "SUPPLIER_UNAVAILABLE")
    await engine.dispose()
