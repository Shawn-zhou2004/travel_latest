import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.mcp.transport import OfferValidation, TransportOffer
from app.integrations.suppliers.mock_transport import DeterministicMockTransportTicketIssuer
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.orders.models import MockTransportTicket, PaymentRecord, TravelOffer, TravelOrder, TravelSearchJob
from app.modules.orders.services import MockTicketService, SupplierFulfillmentUnavailable


class RevalidatingProvider:
    def __init__(self, validation: OfferValidation) -> None:
        self.validation = validation
        self.selected_offer: TransportOffer | None = None

    async def revalidate(self, selected_offer: TransportOffer) -> OfferValidation:
        self.selected_offer = selected_offer
        return self.validation


async def _paid_transport_order(session: object) -> tuple[TravelOrder, PaymentRecord, MockTransportTicket]:
    user = User(phone="13500000005")
    session.add(user)
    await session.flush()
    valid_until = datetime.now(UTC) + timedelta(minutes=10)
    job = TravelSearchJob(user_id=user.id, idempotency_key="transport-search", search_type="train", query_snapshot={"passenger_count": 1}, status="completed", source="magic_mcp")
    session.add(job)
    await session.flush()
    offer = TravelOffer(
        search_job_id=job.id,
        source="magic_mcp",
        external_offer_id="G1234:second",
        title="G1234 second_class",
        amount=Decimal("88.00"),
        currency="CNY",
        availability="available",
        valid_until=valid_until,
        change_rules={},
        snapshot={},
    )
    session.add(offer)
    await session.flush()
    order = TravelOrder(
        user_id=user.id,
        offer_id=offer.id,
        idempotency_key="transport-order",
        amount=offer.amount,
        currency=offer.currency,
        offer_snapshot={
            "source": offer.source,
            "external_offer_id": offer.external_offer_id,
            "origin": "Hangzhou",
            "destination": "Beijing",
            "carrier_number": "G1234",
            "seat_or_cabin_class": "second_class",
            "departure_at": "2026-10-01T08:00:00+08:00",
            "arrival_at": "2026-10-01T12:30:00+08:00",
            "valid_until": valid_until.isoformat(),
        },
        status="PAID_PENDING_FULFILLMENT",
        payment_status="paid",
        fulfillment_status="pending_confirmation",
    )
    session.add(order)
    await session.flush()
    ticket = MockTransportTicket(order_id=order.id, transport_type="train", passenger_facts={"passengers": [{"masked_name": "A*"}]})
    payment = PaymentRecord(order_id=order.id, idempotency_key="transport-payment", provider="alipay_sandbox", amount=order.amount, currency="CNY", status="paid")
    session.add_all([ticket, payment])
    await session.commit()
    return order, payment, ticket


def test_transport_revalidation_unavailable_retries_without_mutating_ticket_or_order() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            order, payment, ticket = await _paid_transport_order(session)
            provider = RevalidatingProvider(OfferValidation(False, "REALTIME_TRANSPORT_UNAVAILABLE", "unavailable"))

            with pytest.raises(SupplierFulfillmentUnavailable):
                await MockTicketService(session, DeterministicMockTransportTicketIssuer(), provider).issue_paid_ticket(payment.id)

            await session.refresh(order)
            await session.refresh(ticket)
            assert (order.status, order.payment_status, order.fulfillment_status) == ("PAID_PENDING_FULFILLMENT", "paid", "pending_confirmation")
            assert ticket.status == "pending"
        await engine.dispose()
    asyncio.run(scenario())


def test_transport_revalidation_mismatch_fails_ticket_while_order_stays_paid_awaiting_refund() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            order, payment, ticket = await _paid_transport_order(session)
            provider = RevalidatingProvider(OfferValidation(False, "OFFER_CHANGED", "changed"))

            issued = await MockTicketService(session, DeterministicMockTransportTicketIssuer(), provider).issue_paid_ticket(payment.id)

            assert issued is ticket
            await session.refresh(order)
            await session.refresh(ticket)
            assert (order.status, order.payment_status, order.fulfillment_status, order.failure_code) == ("TICKET_FAILED_AWAITING_REFUND", "paid", "failed", "OFFER_CHANGED")
            assert (ticket.status, ticket.mock_ticket_no, ticket.failure_code) == ("failed", None, "OFFER_CHANGED")
            assert provider.selected_offer is not None
            assert provider.selected_offer.external_offer_id == "G1234:second"
            assert provider.selected_offer.origin == "Hangzhou"
            audit = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == ticket.id))
            assert audit is not None
            assert "document" not in json.dumps(dict(audit.payload_json)).lower()
        await engine.dispose()
    asyncio.run(scenario())
