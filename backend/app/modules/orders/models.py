from datetime import datetime
from decimal import Decimal
from typing import Mapping

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, new_uuid, utc_now
from app.models.outbox import ImmutableJSON


class TravelSearchJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "travel_search_jobs"
    __table_args__ = (
        CheckConstraint("search_type IN ('train', 'flight', 'hotel', 'ride')", name="ck_travel_search_jobs_type"),
        CheckConstraint("status IN ('pending', 'completed', 'empty', 'failed')", name="ck_travel_search_jobs_status"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_travel_search_jobs_user_key"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    search_type: Mapped[str] = mapped_column(String(16), nullable=False)
    query_snapshot: Mapped[Mapping[str, object]] = mapped_column(ImmutableJSON(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="supplier_unavailable")
    unavailable_code: Mapped[str | None] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


class TravelOffer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "travel_offers"
    __table_args__ = (
        CheckConstraint("availability IN ('available', 'unavailable')", name="ck_travel_offers_availability"),
    )

    search_job_id: Mapped[str] = mapped_column(ForeignKey("travel_search_jobs.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_offer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    change_rules: Mapped[Mapping[str, object]] = mapped_column(ImmutableJSON(), nullable=False)
    snapshot: Mapped[Mapping[str, object]] = mapped_column(ImmutableJSON(), nullable=False)


class TravelOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "travel_orders"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING_CONFIRMATION', 'PAYING', 'PAID_PENDING_FULFILLMENT', 'CONFIRMED', 'FAILED', 'TICKET_FAILED_AWAITING_REFUND', 'REFUNDING', 'REFUNDED', 'CLOSED')", name="ck_travel_orders_status"),
        CheckConstraint("payment_status IN ('pending', 'paying', 'paid', 'failed', 'refunding', 'refunded')", name="ck_travel_orders_payment_status"),
        CheckConstraint("fulfillment_status IN ('pending_confirmation', 'confirming', 'confirmed', 'failed', 'not_supported')", name="ck_travel_orders_fulfillment_status"),
        UniqueConstraint("order_no", name="uq_travel_orders_order_no"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_travel_orders_user_key"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    offer_id: Mapped[str] = mapped_column(ForeignKey("travel_offers.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    order_no: Mapped[str] = mapped_column(String(40), nullable=False, default=lambda: f"TO{new_uuid().replace('-', '')[:24].upper()}")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    offer_snapshot: Mapped[Mapping[str, object]] = mapped_column(ImmutableJSON(), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING_CONFIRMATION")
    payment_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    fulfillment_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_confirmation")
    failure_code: Mapped[str | None] = mapped_column(String(64))


class FulfillmentAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fulfillment_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_fulfillment_attempts_status"),
        CheckConstraint("attempt_count >= 0", name="ck_fulfillment_attempts_attempt_count"),
        # A fulfillment request is retried by updating this durable record, never by creating another request for the order.
        UniqueConstraint("order_id", name="uq_fulfillment_attempts_order"),
        UniqueConstraint("idempotency_key", name="uq_fulfillment_attempts_idempotency_key"),
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("travel_orders.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    external_confirmation_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    redacted_result: Mapped[Mapping[str, object] | None] = mapped_column(ImmutableJSON())
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class MockTransportTicket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A clearly simulated transport ticket; never a supplier-issued credential."""

    __tablename__ = "mock_transport_tickets"
    __table_args__ = (
        CheckConstraint("transport_type IN ('train', 'flight')", name="ck_mock_transport_tickets_type"),
        CheckConstraint("status IN ('pending', 'issued', 'failed')", name="ck_mock_transport_tickets_status"),
        UniqueConstraint("order_id", name="uq_mock_transport_tickets_order"),
        UniqueConstraint("mock_ticket_no", name="uq_mock_transport_tickets_ticket_no"),
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("travel_orders.id"), nullable=False, index=True)
    transport_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    mock_ticket_no: Mapped[str | None] = mapped_column(String(64))
    seat_assignments: Mapped[Mapping[str, object]] = mapped_column(ImmutableJSON(), nullable=False, default=dict)
    passenger_facts: Mapped[Mapping[str, object]] = mapped_column(ImmutableJSON(), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))


class PaymentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_records"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'paying', 'paid', 'failed', 'refunding', 'refunded')", name="ck_payment_records_status"),
        UniqueConstraint("payment_no", name="uq_payment_records_payment_no"),
        UniqueConstraint("order_id", "idempotency_key", name="uq_payment_records_order_key"),
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("travel_orders.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, default=lambda: f"payment:{new_uuid()}")
    payment_no: Mapped[str] = mapped_column(String(40), nullable=False, default=lambda: f"TP{new_uuid().replace('-', '')[:24].upper()}")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    provider_transaction_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class PaymentCallbackEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payment_callback_events"
    __table_args__ = (
        CheckConstraint("verification_status IN ('pending', 'verified', 'rejected')", name="ck_payment_callback_events_verification_status"),
        CheckConstraint("processing_status IN ('pending', 'processed', 'failed')", name="ck_payment_callback_events_processing_status"),
        # MySQL permits multiple NULL values, retaining malformed rejected callbacks without deduping them by a fabricated provider ID.
        UniqueConstraint("provider", "provider_transaction_id", name="uq_payment_callback_provider_tx"),
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(128))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payment_records.id"), index=True)
    raw_payload: Mapped[Mapping[str, object]] = mapped_column(ImmutableJSON(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    verification_error: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    processing_error: Mapped[str | None] = mapped_column(String(255))
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RefundRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refund_records"
    __table_args__ = (
        CheckConstraint("status IN ('requested', 'processing', 'refunded', 'failed')", name="ck_refund_records_status"),
        UniqueConstraint("payment_id", "idempotency_key", name="uq_refund_records_payment_key"),
    )
    payment_id: Mapped[str] = mapped_column(ForeignKey("payment_records.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    refund_no: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, default=lambda: f"TR{new_uuid().replace('-', '')[:24].upper()}")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")
    provider_refund_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_code: Mapped[str | None] = mapped_column(String(64))


_IMMUTABLE_OFFER_FIELDS = ("search_job_id", "source", "external_offer_id", "title", "amount", "currency", "availability", "valid_until", "retrieved_at", "change_rules", "snapshot")


def _prevent_offer_mutation(target: object, value: object, oldvalue: object, initiator: object) -> object:
    if inspect(target).persistent and oldvalue != value:
        raise ValueError("Travel offers are immutable after insert")
    return value


for _field in _IMMUTABLE_OFFER_FIELDS:
    event.listen(getattr(TravelOffer, _field), "set", _prevent_offer_mutation, retval=True)
