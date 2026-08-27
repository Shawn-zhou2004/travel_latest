from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from dataclasses import dataclass
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.alipay.adapter import (
    AlipayAdapter,
    AlipayRefundRequest,
    AlipayWapPaymentRequest,
    TradeQueryResult,
    UnavailableAlipayAdapter,
    VerifiedAlipayCallback,
)
from app.integrations.mcp.transport import OfferValidation, TransportOffer, TransportOfferProvider
from app.integrations.suppliers.client import (
    SupplierAdapter,
    SupplierFulfillmentConfirmationRequest,
    SupplierFulfillmentConfirmationResult,
    SupplierSearchRequest,
)
from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.modules.orders.models import FulfillmentAttempt, MockTransportTicket, PaymentCallbackEvent, PaymentRecord, RefundRecord, TravelOffer, TravelOrder, TravelSearchJob


class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class SupplierFulfillmentUnavailable(RuntimeError):
    """The worker should release the durable claim and let the broker retry."""


@dataclass(frozen=True)
class FulfillmentWork:
    travel_order_id: str
    attempt_id: str
    request: SupplierFulfillmentConfirmationRequest


class SearchService:
    def __init__(self, session: AsyncSession, supplier: SupplierAdapter) -> None:
        self.session = session
        self.supplier = supplier

    async def create(self, user_id: str, idempotency_key: str, request: SupplierSearchRequest) -> TravelSearchJob:
        existing = await self.session.scalar(select(TravelSearchJob).where(TravelSearchJob.user_id == user_id, TravelSearchJob.idempotency_key == idempotency_key))
        if existing:
            return existing
        job = TravelSearchJob(user_id=user_id, idempotency_key=idempotency_key, search_type=request.search_type, query_snapshot={"origin": request.origin, "destination": request.destination, "depart_date": request.depart_date.isoformat(), "passenger_count": request.passenger_count})
        self.session.add(job)
        await self.session.flush()
        result = await self.supplier.search(request)
        job.status = "completed" if result.offers else "empty"
        job.source = result.offers[0].source if result.offers else "supplier_unavailable"
        job.unavailable_code = None if result.available else result.code
        for item in result.offers:
            self.session.add(TravelOffer(
                search_job_id=job.id,
                source=item.source,
                external_offer_id=item.external_offer_id,
                title=item.title,
                amount=Decimal(item.amount),
                currency=item.currency,
                availability=item.availability,
                valid_until=item.valid_until,
                change_rules=item.change_rules,
                snapshot={
                    **item.snapshot,
                    "source": item.source,
                    "external_offer_id": item.external_offer_id,
                    "valid_until": item.valid_until.isoformat(),
                },
            ))
        self.session.add(OutboxEvent(
            event_type="travel_search_job.completed",
            aggregate_type="travel_search_job",
            aggregate_id=job.id,
            trace_id=new_uuid(),
            payload_json={
                "travel_search_job_id": job.id,
                "user_id": user_id,
                "status": job.status,
                "offer_count": len(result.offers),
                "error_code": job.unavailable_code,
            },
        ))
        await self.session.commit()
        return job


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_from_offer(self, user_id: str, offer_id: str, idempotency_key: str, passengers: list[Mapping[str, str]] | None = None) -> TravelOrder:
        existing = await self.session.scalar(select(TravelOrder).where(TravelOrder.user_id == user_id, TravelOrder.idempotency_key == idempotency_key))
        if existing:
            if existing.offer_id != offer_id:
                raise DomainError("IDEMPOTENCY_CONFLICT", "Idempotency-Key is already bound to another offer.")
            return existing
        offer_and_job = await self.session.execute(
            select(TravelOffer, TravelSearchJob)
            .join(TravelSearchJob, TravelSearchJob.id == TravelOffer.search_job_id)
            .where(TravelOffer.id == offer_id, TravelSearchJob.user_id == user_id)
        )
        row = offer_and_job.one_or_none()
        if row is None:
            raise DomainError("OFFER_NOT_FOUND", "The selected offer does not exist.", 404)
        offer, search_job = row
        valid_until = offer.valid_until.replace(tzinfo=UTC) if offer.valid_until.tzinfo is None else offer.valid_until
        if offer.availability != "available":
            raise DomainError("OFFER_UNAVAILABLE", "The selected offer is unavailable.")
        if valid_until <= datetime.now(UTC):
            raise DomainError("OFFER_EXPIRED", "The selected offer has expired.")
        transport_passengers = passengers or []
        if search_job.search_type in {"train", "flight"} and not transport_passengers:
            raise DomainError("PASSENGERS_REQUIRED", "Passenger details are required for transport orders.", 422)
        if search_job.search_type in {"train", "flight"}:
            expected_passenger_count = search_job.query_snapshot.get("passenger_count")
            if (
                not isinstance(expected_passenger_count, int)
                or isinstance(expected_passenger_count, bool)
                or len(transport_passengers) != expected_passenger_count
            ):
                raise DomainError("PASSENGER_COUNT_MISMATCH", "Passenger count must match the transport search.", 422)
        order = TravelOrder(
            user_id=user_id,
            offer_id=offer.id,
            idempotency_key=idempotency_key,
            amount=offer.amount,
            currency=offer.currency,
            offer_snapshot=offer.snapshot,
            status="PENDING_CONFIRMATION",
            payment_status="pending",
            fulfillment_status="pending_confirmation",
        )
        self.session.add(order)
        await self.session.flush()
        if search_job.search_type in {"train", "flight"}:
            self.session.add(MockTransportTicket(
                order_id=order.id,
                transport_type=search_job.search_type,
                passenger_facts={"passengers": [_masked_passenger_facts(passenger) for passenger in transport_passengers]},
            ))
        self.session.add(OutboxEvent(
            event_type="travel_order.created",
            aggregate_type="travel_order",
            aggregate_id=order.id,
            trace_id=new_uuid(),
            payload_json={
                "travel_order_id": order.id,
                "user_id": user_id,
                "order_no": order.order_no,
                "status": order.status,
                "payment_status": order.payment_status,
                "fulfillment_status": order.fulfillment_status,
            },
        ))
        await self.session.commit()
        return order


class OrderStateService:
    """Keeps independent order dimensions from being advanced by client input."""

    _allowed = {
        ("PENDING_CONFIRMATION", "pending", "pending_confirmation"): {
            ("PAYING", "paying", "pending_confirmation"),
            ("FAILED", "failed", "not_supported"),
        },
        ("PAYING", "paying", "pending_confirmation"): {
            ("PAID_PENDING_FULFILLMENT", "paid", "pending_confirmation"),
            ("FAILED", "failed", "not_supported"),
        },
        ("PAID_PENDING_FULFILLMENT", "paid", "pending_confirmation"): {
            ("PAID_PENDING_FULFILLMENT", "paid", "confirming"),
            ("CONFIRMED", "paid", "confirmed"),
            ("REFUNDING", "refunding", "pending_confirmation"),
            ("FAILED", "failed", "failed"),
            ("TICKET_FAILED_AWAITING_REFUND", "paid", "failed"),
        },
        ("PAID_PENDING_FULFILLMENT", "paid", "confirming"): {
            ("PAID_PENDING_FULFILLMENT", "paid", "pending_confirmation"),
            ("CONFIRMED", "paid", "confirmed"),
            ("FAILED", "failed", "failed"),
            ("TICKET_FAILED_AWAITING_REFUND", "paid", "failed"),
        },
        ("TICKET_FAILED_AWAITING_REFUND", "paid", "failed"): {
            ("REFUNDING", "refunding", "failed"),
        },
        ("REFUNDING", "refunding", "failed"): {
            ("REFUNDED", "refunded", "failed"),
            ("TICKET_FAILED_AWAITING_REFUND", "paid", "failed"),
        },
        ("REFUNDING", "refunding", "pending_confirmation"): {
            ("REFUNDED", "refunded", "not_supported"),
            ("FAILED", "failed", "failed"),
        },
    }

    def transition(
        self,
        order: TravelOrder,
        *,
        actor_user_id: str | None,
        status: str,
        payment_status: str,
        fulfillment_status: str,
    ) -> None:
        if actor_user_id is not None and actor_user_id != order.user_id:
            raise DomainError("FORBIDDEN", "This actor cannot transition the order.", 403)
        target = (status, payment_status, fulfillment_status)
        current = (order.status, order.payment_status, order.fulfillment_status)
        if target not in self._allowed.get(current, set()):
            raise DomainError("INVALID_ORDER_TRANSITION", "The requested order transition is not allowed.")
        order.status, order.payment_status, order.fulfillment_status = target


def _masked_passenger_facts(passenger: Mapping[str, str]) -> dict[str, str]:
    name = passenger["name"].strip()
    document_number = passenger["document_number"].strip()
    return {
        "masked_name": f"{name[:1]}{'*' * max(len(name) - 1, 1)}",
        "document_type": passenger["document_type"],
        "masked_document_number": f"{'*' * max(len(document_number) - 4, 4)}{document_number[-4:]}",
        "seat_preference": passenger["seat_preference"],
    }


class MockTicketService:
    """Worker-facing seam for mock ticket issuance after a verified payment."""

    def __init__(self, session: AsyncSession, issuer: object, offer_provider: TransportOfferProvider | None = None) -> None:
        self.session = session
        self.issuer = issuer
        self.offer_provider = offer_provider

    async def issue_paid_ticket(self, payment_id: str) -> MockTransportTicket | None:
        payment = await self.session.scalar(select(PaymentRecord).where(PaymentRecord.id == payment_id).with_for_update())
        if payment is None or payment.status != "paid":
            return None
        order = await self.session.get(TravelOrder, payment.order_id, with_for_update=True)
        if order is None or (order.status, order.payment_status) != ("PAID_PENDING_FULFILLMENT", "paid"):
            return None
        ticket = await self.session.scalar(select(MockTransportTicket).where(MockTransportTicket.order_id == order.id).with_for_update())
        if ticket is None or ticket.status != "pending":
            return ticket
        if self.offer_provider is not None:
            try:
                validation = await self.offer_provider.revalidate(self._selected_offer(order, ticket))
            except Exception as error:
                raise SupplierFulfillmentUnavailable("Transport offer validation is temporarily unavailable.") from error
            if validation.code == "REALTIME_TRANSPORT_UNAVAILABLE":
                raise SupplierFulfillmentUnavailable("Transport offer validation is temporarily unavailable.")
            if not validation.valid:
                return await self._fail_ticket(order, ticket, validation)
        result = await self.issuer.issue(ticket)
        if result.issued:
            ticket.status = "issued"
            ticket.mock_ticket_no = result.mock_ticket_no
            ticket.seat_assignments = result.seat_assignments
            OrderStateService().transition(order, actor_user_id=None, status="CONFIRMED", payment_status="paid", fulfillment_status="confirmed")
            order.failure_code = None
        else:
            return await self._fail_ticket(order, ticket, OfferValidation(False, result.code, "Mock ticket issuance failed."))
        self.session.add(OutboxEvent(
            event_type="mock_transport_ticket.updated",
            aggregate_type="mock_transport_ticket",
            aggregate_id=ticket.id,
            trace_id=new_uuid(),
            payload_json={"mock_transport_ticket_id": ticket.id, "travel_order_id": order.id, "user_id": order.user_id, "status": ticket.status, "failure_code": ticket.failure_code},
        ))
        await self.session.commit()
        return ticket

    @staticmethod
    def _selected_offer(order: TravelOrder, ticket: MockTransportTicket) -> TransportOffer:
        snapshot = order.offer_snapshot
        return TransportOffer(
            source=str(snapshot.get("source") or ""),
            external_offer_id=str(snapshot["external_offer_id"]),
            transport_type=ticket.transport_type,  # type: ignore[arg-type]
            origin=str(snapshot["origin"]),
            destination=str(snapshot["destination"]),
            carrier_number=str(snapshot["carrier_number"]),
            seat_or_cabin_class=str(snapshot["seat_or_cabin_class"]),
            availability="available",
            amount=order.amount,
            currency=order.currency,
            departure_at=datetime.fromisoformat(str(snapshot["departure_at"]).replace("Z", "+00:00")),
            arrival_at=datetime.fromisoformat(str(snapshot["arrival_at"]).replace("Z", "+00:00")),
            valid_until=datetime.fromisoformat(str(snapshot["valid_until"]).replace("Z", "+00:00")),
            retrieved_at=datetime.now(UTC),
            change_rules={},
        )

    async def _fail_ticket(
        self,
        order: TravelOrder,
        ticket: MockTransportTicket,
        validation: OfferValidation,
    ) -> MockTransportTicket:
        ticket.status = "failed"
        ticket.mock_ticket_no = None
        ticket.seat_assignments = {}
        ticket.failure_code = validation.code[:64] or "MOCK_TICKET_ISSUANCE_FAILED"
        OrderStateService().transition(order, actor_user_id=None, status="TICKET_FAILED_AWAITING_REFUND", payment_status="paid", fulfillment_status="failed")
        order.failure_code = ticket.failure_code
        self.session.add(OutboxEvent(
            event_type="mock_transport_ticket.updated",
            aggregate_type="mock_transport_ticket",
            aggregate_id=ticket.id,
            trace_id=new_uuid(),
            payload_json={"mock_transport_ticket_id": ticket.id, "travel_order_id": order.id, "user_id": order.user_id, "status": ticket.status, "failure_code": ticket.failure_code},
        ))
        await self.session.commit()
        return ticket


class FulfillmentService:
    def __init__(self, session: AsyncSession, supplier: SupplierAdapter) -> None:
        self.session = session
        self.supplier = supplier

    async def start_attempt(self, payment_id: str) -> FulfillmentWork | None:
        payment = await self.session.scalar(
            select(PaymentRecord).where(PaymentRecord.id == payment_id).with_for_update()
        )
        if payment is None or payment.status != "paid":
            return None
        order = await self.session.get(TravelOrder, payment.order_id, with_for_update=True)
        if order is None or order.status != "PAID_PENDING_FULFILLMENT" or order.payment_status != "paid":
            return None
        attempt = await self.session.scalar(
            select(FulfillmentAttempt).where(FulfillmentAttempt.order_id == order.id).with_for_update()
        )
        resuming = order.fulfillment_status == "confirming" and attempt is not None and attempt.status == "running"
        if order.fulfillment_status != "pending_confirmation" and not resuming:
            return None
        if attempt is None:
            source = order.offer_snapshot.get("source")
            offer = await self.session.get(TravelOffer, order.offer_id)
            if offer is None:
                return None
            attempt = FulfillmentAttempt(
                order_id=order.id,
                source=offer.source,
                idempotency_key=f"fulfillment:{order.id}",
            )
            self.session.add(attempt)
            await self.session.flush()
        if not resuming and attempt.status != "queued":
            return None
        if not resuming:
            OrderStateService().transition(
                order,
                actor_user_id=None,
                status="PAID_PENDING_FULFILLMENT",
                payment_status="paid",
                fulfillment_status="confirming",
            )
            attempt.status = "running"
            attempt.attempt_count += 1
            attempt.started_at = attempt.started_at or utc_now()
            attempt.failure_code = None
        attempt.last_attempt_at = utc_now()
        await self.session.flush()
        return FulfillmentWork(
            travel_order_id=order.id,
            attempt_id=attempt.id,
            request=SupplierFulfillmentConfirmationRequest(
                source=attempt.source,
                external_offer_id=offer.external_offer_id,
                order_reference=order.order_no,
                idempotency_key=f"fulfillment:{order.id}",
            ),
        )

    async def confirm(self, attempt: FulfillmentWork) -> None:
        try:
            result = await self.supplier.confirm_fulfillment(attempt.request)
        except Exception as error:
            raise SupplierFulfillmentUnavailable("Supplier confirmation is temporarily unavailable.") from error
        if not isinstance(result, SupplierFulfillmentConfirmationResult):
            raise SupplierFulfillmentUnavailable("Supplier returned an invalid confirmation result.")
        if result.confirmed:
            await self._complete(attempt, "CONFIRMED", "confirmed", None, result)
        elif result.code == "SUPPLIER_UNAVAILABLE":
            raise SupplierFulfillmentUnavailable("Supplier confirmation is temporarily unavailable.")
        else:
            await self._complete(attempt, "FAILED", "failed", result.code[:64] or "SUPPLIER_CONFIRMATION_FAILED", result)

    async def prepare_retry(self, travel_order_id: str) -> None:
        order = await self.session.get(TravelOrder, travel_order_id, with_for_update=True)
        if order is None or order.fulfillment_status != "confirming":
            return
        attempt = await self.session.scalar(
            select(FulfillmentAttempt).where(FulfillmentAttempt.order_id == travel_order_id).with_for_update()
        )
        OrderStateService().transition(
            order,
            actor_user_id=None,
            status="PAID_PENDING_FULFILLMENT",
            payment_status="paid",
            fulfillment_status="pending_confirmation",
        )
        order.failure_code = "SUPPLIER_UNAVAILABLE"
        if attempt is not None and attempt.status == "running":
            attempt.status = "queued"
            attempt.failure_code = "SUPPLIER_UNAVAILABLE"
        await self.session.commit()

    async def _complete(
        self,
        work: FulfillmentWork,
        status: str,
        fulfillment_status: str,
        failure_code: str | None,
        result: SupplierFulfillmentConfirmationResult,
    ) -> None:
        order = await self.session.get(TravelOrder, work.travel_order_id, with_for_update=True)
        if order is None or order.fulfillment_status != "confirming":
            return
        attempt = await self.session.get(FulfillmentAttempt, work.attempt_id, with_for_update=True)
        if attempt is None or attempt.status != "running":
            return
        OrderStateService().transition(
            order,
            actor_user_id=None,
            status=status,
            payment_status="paid" if status == "CONFIRMED" else "failed",
            fulfillment_status=fulfillment_status,
        )
        order.failure_code = failure_code
        attempt.status = "succeeded" if status == "CONFIRMED" else "failed"
        attempt.failure_code = failure_code
        attempt.external_confirmation_id = result.supplier_confirmation_id
        attempt.redacted_result = {"confirmed": result.confirmed, "code": result.code}
        attempt.completed_at = utc_now()
        self.session.add(OutboxEvent(
            event_type="travel_order.fulfillment_updated",
            aggregate_type="travel_order",
            aggregate_id=order.id,
            trace_id=new_uuid(),
            payload_json={
                "travel_order_id": order.id,
                "user_id": order.user_id,
                "status": order.status,
                "payment_status": order.payment_status,
                "fulfillment_status": order.fulfillment_status,
                "failure_code": order.failure_code,
            },
        ))
        await self.session.commit()


REFUND_REQUESTED_EVENT = "refund_record.requested"
REFUND_UPDATED_EVENT = "refund_record.updated"


class RefundService:
    def __init__(self, session: AsyncSession, adapter: AlipayAdapter | None = None) -> None:
        self.session = session
        self.adapter = adapter

    def _require_adapter(self) -> AlipayAdapter:
        if self.adapter is None or isinstance(self.adapter, UnavailableAlipayAdapter):
            raise DomainError("PAYMENT_NOT_CONFIGURED", "Alipay is not configured.", 503)
        return self.adapter

    async def create(self, order_id: str, requester_id: str, idempotency_key: str, amount: Decimal, currency: str, reason: str) -> RefundRecord:
        self._require_adapter()
        order = await self.session.scalar(select(TravelOrder).where(TravelOrder.id == order_id).with_for_update())
        if order is None or order.user_id != requester_id:
            raise DomainError("ORDER_NOT_FOUND", "Order not found.", 404)
        payment = await self.session.scalar(select(PaymentRecord).where(PaymentRecord.order_id == order.id, PaymentRecord.status == "paid").with_for_update())
        if payment is None:
            raise DomainError("REFUND_NOT_ALLOWED", "The order has no settled payment.")
        existing = await self.session.scalar(select(RefundRecord).where(RefundRecord.payment_id == payment.id, RefundRecord.idempotency_key == idempotency_key))
        if existing is not None:
            return existing
        if (order.status, order.payment_status, order.fulfillment_status) not in {
            ("PAID_PENDING_FULFILLMENT", "paid", "pending_confirmation"),
            ("TICKET_FAILED_AWAITING_REFUND", "paid", "failed"),
        }:
            raise DomainError("REFUND_NOT_ALLOWED", "This order cannot be refunded in its current state.")
        if currency != "CNY" or amount != order.amount:
            raise DomainError("REFUND_AMOUNT_INVALID", "Only the full paid CNY amount can be refunded.")
        active = await self.session.scalar(select(RefundRecord).where(RefundRecord.payment_id == payment.id, RefundRecord.status.in_(("requested", "processing"))))
        if active is not None:
            raise DomainError("REFUND_IN_PROGRESS", "An active refund already exists for this payment.")
        refund = RefundRecord(payment_id=payment.id, idempotency_key=idempotency_key, amount=amount, currency=currency, reason=reason, requested_by=requester_id, status="requested")
        self.session.add(refund)
        await self.session.flush()
        OrderStateService().transition(
            order,
            actor_user_id=None,
            status="REFUNDING",
            payment_status="refunding",
            fulfillment_status="failed" if order.fulfillment_status == "failed" else "pending_confirmation",
        )
        self.session.add(OutboxEvent(event_type=REFUND_REQUESTED_EVENT, aggregate_type="refund_record", aggregate_id=refund.id, trace_id=new_uuid(), payload_json={"refund_id": refund.id}))
        await self.session.commit()
        return refund

    async def process(self, refund_id: str) -> None:
        adapter = self._require_adapter()
        refund = await self.session.scalar(select(RefundRecord).where(RefundRecord.id == refund_id).with_for_update())
        if refund is None or refund.status in {"refunded", "failed"}:
            return
        payment = await self.session.get(PaymentRecord, refund.payment_id)
        if payment is None:
            return
        refund.status = "processing"
        await self.session.commit()
        try:
            result = await adapter.refund_trade(AlipayRefundRequest(out_trade_no=payment.payment_no, refund_amount=refund.amount, out_request_no=refund.refund_no, refund_reason=refund.reason))
        except Exception as error:
            raise DomainError("REFUND_PROVIDER_UNAVAILABLE", "Alipay refund is temporarily unavailable.", 503) from error
        refund = await self.session.scalar(select(RefundRecord).where(RefundRecord.id == refund_id).with_for_update())
        payment = await self.session.get(PaymentRecord, refund.payment_id) if refund else None
        order = await self.session.get(TravelOrder, payment.order_id, with_for_update=True) if payment else None
        if refund is None or payment is None or order is None:
            return
        valid = result.gateway_code == "10000" and result.out_trade_no == payment.payment_no and result.out_request_no == refund.refund_no and result.refund_fee == refund.amount and result.fund_change == "Y"
        if valid:
            refund.status, refund.provider_refund_id, refund.completed_at, refund.failure_code = "refunded", result.trade_no, utc_now(), None
            OrderStateService().transition(
                order,
                actor_user_id=None,
                status="REFUNDED",
                payment_status="refunded",
                fulfillment_status="failed" if order.fulfillment_status == "failed" else "not_supported",
            )
        else:
            refund.status, refund.completed_at, refund.failure_code = "failed", utc_now(), "REFUND_PROVIDER_REJECTED"
            if order.fulfillment_status == "failed":
                OrderStateService().transition(
                    order,
                    actor_user_id=None,
                    status="TICKET_FAILED_AWAITING_REFUND",
                    payment_status="paid",
                    fulfillment_status="failed",
                )
            else:
                order.status, order.payment_status, order.fulfillment_status = "FAILED", "failed", "failed"
            order.failure_code = "REFUND_PROVIDER_REJECTED"
        self.session.add(OutboxEvent(event_type=REFUND_UPDATED_EVENT, aggregate_type="refund_record", aggregate_id=refund.id, trace_id=new_uuid(), payload_json={"refund_id": refund.id, "travel_order_id": order.id, "user_id": order.user_id, "status": refund.status, "failure_code": refund.failure_code}))
        await self.session.commit()


class PaymentService:
    def __init__(self, session: AsyncSession, adapter: AlipayAdapter | None = None) -> None:
        self.session = session
        self.adapter = adapter

    @staticmethod
    def payment_no_for(order_id: str, idempotency_key: str) -> str:
        return f"TP{sha256(f'{order_id}:{idempotency_key}'.encode()).hexdigest()[:32].upper()}"

    def _require_adapter(self) -> AlipayAdapter:
        if self.adapter is None or isinstance(self.adapter, UnavailableAlipayAdapter):
            raise DomainError("PAYMENT_NOT_CONFIGURED", "Alipay is not configured.", 503)
        return self.adapter

    async def create_checkout(self, order: TravelOrder, idempotency_key: str) -> tuple[PaymentRecord, str]:
        adapter = self._require_adapter()
        locked_order = await self.session.scalar(
            select(TravelOrder).where(TravelOrder.id == order.id).with_for_update()
        )
        if locked_order is None:
            raise DomainError("ORDER_NOT_FOUND", "Order not found.", 404)
        order = locked_order
        if order.status not in {"PENDING_CONFIRMATION", "PAYING"} or order.payment_status not in {"pending", "paying"}:
            raise DomainError("PAYMENT_NOT_ALLOWED", "A payment cannot be created for this order state.")
        if order.currency != "CNY":
            raise DomainError("PAYMENT_NOT_ALLOWED", "Alipay payments require CNY.")
        payment = await self.session.scalar(
            select(PaymentRecord).where(PaymentRecord.order_id == order.id, PaymentRecord.idempotency_key == idempotency_key)
        )
        active_payment = await self.session.scalar(
            select(PaymentRecord).where(
                PaymentRecord.order_id == order.id,
                PaymentRecord.status.in_(("pending", "paying")),
            )
        )
        if payment is None:
            if active_payment is not None:
                raise DomainError("PAYMENT_IN_PROGRESS", "An active payment already exists for this order.")
            payment = PaymentRecord(
                order_id=order.id,
                idempotency_key=idempotency_key,
                payment_no=self.payment_no_for(order.id, idempotency_key),
                provider="alipay_sandbox",
                amount=order.amount,
                currency=order.currency,
                status="paying",
            )
            self.session.add(payment)
            if order.status == "PENDING_CONFIRMATION":
                OrderStateService().transition(
                    order,
                    actor_user_id=order.user_id,
                    status="PAYING",
                    payment_status="paying",
                    fulfillment_status="pending_confirmation",
                )
            await self.session.commit()
        try:
            redirect = await adapter.create_wap_redirect(AlipayWapPaymentRequest(
                out_trade_no=payment.payment_no,
                total_amount=payment.amount,
                subject=f"Travel order {order.order_no}",
            ))
        except Exception as error:
            raise DomainError("PAYMENT_PROVIDER_UNAVAILABLE", "Alipay checkout is temporarily unavailable.", 503) from error
        if not redirect.url.startswith(("https://", "http://")):
            raise DomainError("PAYMENT_PROVIDER_INVALID_RESPONSE", "Alipay returned an invalid checkout response.", 503)
        return payment, redirect.url

    @staticmethod
    def _safe_callback_facts(callback: VerifiedAlipayCallback) -> dict[str, object]:
        return {
            "out_trade_no": callback.out_trade_no,
            "trade_no": callback.trade_no,
            "trade_status": callback.trade_status,
            "total_amount": str(callback.total_amount),
        }

    async def _record_rejected_callback(self, payload: Mapping[str, str]) -> None:
        # An unauthenticated trade number must never reserve the verified callback unique key.
        safe_facts = {key: payload[key] for key in ("app_id", "out_trade_no", "trade_no", "trade_status", "total_amount") if payload.get(key)}
        self.session.add(PaymentCallbackEvent(
            provider="alipay_sandbox", provider_transaction_id=None, payment_id=None,
            raw_payload=safe_facts, verification_status="rejected", verification_error="callback_verification_failed",
            processing_status="failed", processing_error="callback_verification_failed",
        ))
        await self.session.commit()

    async def _record_verified_callback_failure(self, callback: VerifiedAlipayCallback) -> None:
        existing = await self.session.scalar(select(PaymentCallbackEvent).where(
            PaymentCallbackEvent.provider == "alipay_sandbox",
            PaymentCallbackEvent.provider_transaction_id == callback.trade_no,
        ))
        if existing is None:
            self.session.add(PaymentCallbackEvent(
                provider="alipay_sandbox", provider_transaction_id=callback.trade_no, payment_id=None,
                raw_payload=self._safe_callback_facts(callback), verification_status="verified", verified_at=datetime.now(UTC),
                processing_status="failed", processing_error="callback_facts_invalid",
            ))
            await self.session.commit()

    async def _settle(self, verified_callback: VerifiedAlipayCallback, *, callback_app_id: str | None = None, require_callback_app_id: bool = False) -> TravelOrder:
        adapter = self._require_adapter()
        adapter_app_id = getattr(adapter, "app_id", None)
        if (
            verified_callback.trade_status not in {"TRADE_SUCCESS", "TRADE_FINISHED"}
            or not verified_callback.out_trade_no
            or not verified_callback.trade_no
            or verified_callback.total_amount <= 0
            or (require_callback_app_id and (not callback_app_id or callback_app_id != adapter_app_id))
        ):
            raise DomainError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        payment = await self.session.scalar(
            select(PaymentRecord).where(PaymentRecord.provider == "alipay_sandbox", PaymentRecord.payment_no == verified_callback.out_trade_no).with_for_update()
        )
        if payment is None or payment.amount != verified_callback.total_amount:
            raise DomainError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        if payment.provider_transaction_id and payment.provider_transaction_id != verified_callback.trade_no:
            raise DomainError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        order = await self.session.get(TravelOrder, payment.order_id, with_for_update=True)
        if order is None or order.currency != "CNY" or order.currency != payment.currency:
            raise DomainError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)

        callback = await self.session.scalar(
            select(PaymentCallbackEvent).where(
                PaymentCallbackEvent.provider == "alipay_sandbox",
                PaymentCallbackEvent.provider_transaction_id == verified_callback.trade_no,
            )
        )
        if callback is None:
            callback = PaymentCallbackEvent(
                provider="alipay_sandbox", provider_transaction_id=verified_callback.trade_no, payment_id=payment.id,
                raw_payload=self._safe_callback_facts(verified_callback), verification_status="verified", verified_at=datetime.now(UTC),
            )
            self.session.add(callback)
        elif callback.payment_id != payment.id:
            raise DomainError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        if payment.status != "paid":
            payment.status = "paid"
            payment.provider_transaction_id = verified_callback.trade_no
            payment.paid_at = datetime.now(UTC)
            if order.status == "PAYING":
                OrderStateService().transition(order, actor_user_id=None, status="PAID_PENDING_FULFILLMENT", payment_status="paid", fulfillment_status="pending_confirmation")
            self.session.add(OutboxEvent(
                event_type="payment_record.paid",
                aggregate_type="payment_record",
                aggregate_id=payment.id,
                trace_id=new_uuid(),
                payload_json={"payment_id": payment.id, "travel_order_id": order.id, "user_id": order.user_id, "payment_status": "paid"},
            ))
        callback.processing_status = "processed"
        callback.processing_error = None
        callback.processed_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.commit()
        return order

    async def handle_callback(self, payload: Mapping[str, str]) -> TravelOrder:
        adapter = self._require_adapter()
        try:
            verified = await adapter.verify_callback(payload)
        except Exception:
            verified = None
        if verified is None:
            await self._record_rejected_callback(payload)
            raise DomainError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        try:
            return await self._settle(verified, callback_app_id=payload.get("app_id"), require_callback_app_id=True)
        except DomainError:
            await self._record_verified_callback_failure(verified)
            raise

    async def query_order_payment(self, order: TravelOrder) -> TravelOrder:
        payment = await self.session.scalar(
            select(PaymentRecord).where(PaymentRecord.order_id == order.id).order_by(PaymentRecord.created_at.desc())
        )
        if payment is None or payment.status in {"paid", "failed", "refunded"}:
            return order
        adapter = self._require_adapter()
        try:
            result = await adapter.query_trade(payment.payment_no)
        except Exception as error:
            raise DomainError("PAYMENT_PROVIDER_UNAVAILABLE", "Alipay payment query is temporarily unavailable.", 503) from error
        if not isinstance(result, TradeQueryResult):
            raise DomainError("PAYMENT_PROVIDER_INVALID_RESPONSE", "Alipay returned an invalid payment response.", 503)
        if (
            result.gateway_code == "10000"
            and result.trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"}
            and result.out_trade_no == payment.payment_no
            and result.trade_no
            and result.total_amount is not None
        ):
            return await self._settle(VerifiedAlipayCallback(
                out_trade_no=result.out_trade_no, trade_no=result.trade_no,
                trade_status=result.trade_status, total_amount=result.total_amount,
            ))
        return order
