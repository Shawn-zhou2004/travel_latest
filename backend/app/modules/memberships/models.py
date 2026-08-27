from datetime import datetime

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class MembershipPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "membership_plans"
    __table_args__ = (
        CheckConstraint("duration_days > 0", name="ck_membership_plans_duration_days"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_membership_plans_status"),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    entitlement_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    generation_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assistant_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    purchasable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UserMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_memberships"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="ck_user_memberships_status"),
        CheckConstraint("grant_source IN ('admin_grant', 'membership_purchase')", name="ck_user_memberships_grant_source"),
        CheckConstraint("valid_until > valid_from", name="ck_user_memberships_valid_window"),
        UniqueConstraint("granted_by", "idempotency_key", name="uq_user_memberships_granter_key"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("membership_plans.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    grant_source: Mapped[str] = mapped_column(String(32), nullable=False, default="admin_grant")
    granted_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    revoked_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoke_reason: Mapped[str | None] = mapped_column(String(500))


class UserEntitlement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_entitlements"
    __table_args__ = (
        CheckConstraint("valid_until > valid_from", name="ck_user_entitlements_valid_window"),
        UniqueConstraint("membership_id", "entitlement_code", name="uq_user_entitlements_membership_code"),
    )

    membership_id: Mapped[str] = mapped_column(
        ForeignKey("user_memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    entitlement_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
