from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now
from app.models.outbox import ImmutableJSON


class MembershipPurchase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "membership_purchases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_payment', 'paid', 'closed')",
            name="ck_membership_purchases_status",
        ),
        CheckConstraint(
            "payment_status IN ('pending', 'paying', 'paid', 'failed')",
            name="ck_membership_purchases_payment_status",
        ),
        CheckConstraint(
            "authorization_status IN ('pending', 'authorized', 'failed')",
            name="ck_membership_purchases_authorization_status",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_membership_purchases_user_idempotency"),
        UniqueConstraint("payment_no", name="uq_membership_purchases_payment_no"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    membership_plan_id: Mapped[str] = mapped_column(ForeignKey("membership_plans.id"), nullable=False, index=True)
    plan_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_payment", index=True)
    payment_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    authorization_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payment_no: Mapped[str | None] = mapped_column(String(40), unique=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    current_payment_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("membership_payment_attempts.id"), index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    authorized_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    current_payment_attempt: Mapped["MembershipPaymentAttempt | None"] = relationship(
        foreign_keys=[current_payment_attempt_id], post_update=True
    )

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", "pending_payment")
        kwargs.setdefault("payment_status", "pending")
        kwargs.setdefault("authorization_status", "pending")
        super().__init__(**kwargs)


class MembershipPaymentAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "membership_payment_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'paying', 'paid', 'expired', 'closed', 'failed')",
            name="ck_membership_payment_attempts_status",
        ),
        UniqueConstraint("payment_no", name="uq_membership_payment_attempts_payment_no"),
    )

    membership_purchase_id: Mapped[str] = mapped_column(
        ForeignKey("membership_purchases.id"), nullable=False, index=True
    )
    payment_no: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    qr_code: Mapped[str | None] = mapped_column(String(2048))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    membership_purchase: Mapped[MembershipPurchase] = relationship(
        foreign_keys=[membership_purchase_id]
    )

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", "pending")
        super().__init__(**kwargs)


class MembershipPaymentCallbackEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "membership_payment_callback_events"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('pending', 'verified', 'rejected')",
            name="ck_membership_payment_callbacks_verification_status",
        ),
        CheckConstraint(
            "processing_status IN ('pending', 'processed', 'failed')",
            name="ck_membership_payment_callbacks_processing_status",
        ),
        UniqueConstraint(
            "provider", "provider_transaction_id", name="uq_membership_payment_callbacks_provider_tx"
        ),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(128))
    membership_purchase_id: Mapped[str | None] = mapped_column(
        ForeignKey("membership_purchases.id"), index=True
    )
    raw_payload: Mapped[dict[str, object]] = mapped_column(ImmutableJSON(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    verification_error: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    processing_error: Mapped[str | None] = mapped_column(String(255))
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AIQuotaPeriod(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_quota_periods"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('free', 'membership_purchase')",
            name="ck_ai_quota_periods_source_type",
        ),
        CheckConstraint("period_end > period_start", name="ck_ai_quota_periods_window"),
        CheckConstraint(
            "generation_used >= 0 AND generation_used <= generation_limit",
            name="ck_ai_quota_generation_bounds",
        ),
        CheckConstraint(
            "assistant_used >= 0 AND assistant_used <= assistant_limit",
            name="ck_ai_quota_assistant_bounds",
        ),
        UniqueConstraint("membership_purchase_id", name="uq_ai_quota_periods_purchase"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    membership_purchase_id: Mapped[str | None] = mapped_column(
        ForeignKey("membership_purchases.id"), index=True
    )
    period_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    generation_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assistant_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
