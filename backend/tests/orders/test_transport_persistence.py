import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.suppliers.mock_transport import MockTicketIssueResult
from app.models.base import Base
from app.models.user import User
from app.modules.orders.models import MockTransportTicket, PaymentRecord, TravelOffer, TravelOrder, TravelSearchJob
from app.modules.orders.services import DomainError, MockTicketService, OrderService


class FailingIssuer:
    async def issue(self, _ticket: MockTransportTicket) -> MockTicketIssueResult:
        return MockTicketIssueResult(False, "OFFER_SOLD_OUT")


def test_transport_offer_must_belong_to_order_owner_and_only_masked_passenger_facts_persist() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            owner, other = User(phone="13500000001"), User(phone="13500000002")
            session.add_all([owner, other])
            await session.flush()
            job = TravelSearchJob(user_id=owner.id, idempotency_key="train-search", search_type="train", query_snapshot={"passenger_count": 1}, status="completed", source="mock")
            session.add(job)
            await session.flush()
            offer = TravelOffer(search_job_id=job.id, source="mock", external_offer_id="G123", title="G123 second class", amount=Decimal("88.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={})
            session.add(offer)
            await session.commit()

            with pytest.raises(DomainError) as unauthorized:
                await OrderService(session).create_from_offer(other.id, offer.id, "cross-user", [])
            assert unauthorized.value.code == "OFFER_NOT_FOUND"

            document_number = "110101199001011234"
            order = await OrderService(session).create_from_offer(owner.id, offer.id, "owner-order", [{"name": "Alice", "document_type": "identity_card", "document_number": document_number, "seat_preference": "window"}])
            ticket = await session.scalar(select(MockTransportTicket).where(MockTransportTicket.order_id == order.id))
            assert ticket is not None
            facts = ticket.passenger_facts["passengers"][0]
            assert facts["masked_name"] == "A****"
            assert facts["masked_document_number"] == "**************1234"
            assert document_number not in str(ticket.passenger_facts)
        await engine.dispose()
    asyncio.run(scenario())


def test_paid_ticket_failure_awaits_refund_without_wiring_a_worker() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = User(phone="13500000003")
            session.add(user)
            await session.flush()
            job = TravelSearchJob(user_id=user.id, idempotency_key="ticket-search", search_type="train", query_snapshot={"passenger_count": 1}, status="completed", source="mock")
            session.add(job)
            await session.flush()
            offer = TravelOffer(search_job_id=job.id, source="mock", external_offer_id="G456", title="G456 second class", amount=Decimal("88.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={})
            session.add(offer)
            await session.commit()
            order = await OrderService(session).create_from_offer(user.id, offer.id, "ticket-order", [{"name": "Bob", "document_type": "passport", "document_number": "E12345678", "seat_preference": "none"}])
            order.status, order.payment_status = "PAID_PENDING_FULFILLMENT", "paid"
            payment = PaymentRecord(order_id=order.id, idempotency_key="ticket-payment", provider="alipay_sandbox", amount=order.amount, currency="CNY", status="paid")
            session.add(payment)
            await session.commit()

            ticket = await MockTicketService(session, FailingIssuer()).issue_paid_ticket(payment.id)
            assert ticket is not None and ticket.status == "failed"
            await session.refresh(order)
            assert (order.status, order.payment_status, order.fulfillment_status, order.failure_code) == ("TICKET_FAILED_AWAITING_REFUND", "paid", "failed", "OFFER_SOLD_OUT")
        await engine.dispose()
    asyncio.run(scenario())


def test_transport_order_passenger_count_must_match_search_snapshot() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = User(phone="13500000004")
            session.add(user)
            await session.flush()
            job = TravelSearchJob(user_id=user.id, idempotency_key="count-search", search_type="flight", query_snapshot={"passenger_count": 2}, status="completed", source="mock")
            session.add(job)
            await session.flush()
            offer = TravelOffer(search_job_id=job.id, source="mock", external_offer_id="MU123", title="MU123 economy", amount=Decimal("88.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={})
            session.add(offer)
            await session.commit()

            with pytest.raises(DomainError) as error:
                await OrderService(session).create_from_offer(user.id, offer.id, "count-order", [{"name": "Alice", "document_type": "passport", "document_number": "E12345678", "seat_preference": "none"}])
            assert error.value.code == "PASSENGER_COUNT_MISMATCH"
        await engine.dispose()
    asyncio.run(scenario())
