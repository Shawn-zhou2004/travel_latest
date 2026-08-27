import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.membership_purchases.models import AIQuotaPeriod, MembershipPaymentAttempt, MembershipPurchase
from app.modules.memberships.models import MembershipPlan


def test_membership_purchase_snapshots_plan_price_and_quotas() -> None:
    purchase = MembershipPurchase(
        user_id=str(uuid.uuid4()),
        membership_plan_id=str(uuid.uuid4()),
        plan_name_snapshot="AI planning membership",
        amount=Decimal("19.90"),
        currency="CNY",
        duration_days=30,
        generation_quota=10,
        assistant_quota=300,
        idempotency_key="purchase-key",
    )

    assert purchase.amount == Decimal("19.90")
    assert purchase.generation_quota == 10
    assert purchase.assistant_quota == 300
    assert purchase.status == "pending_payment"
    assert purchase.authorization_status == "pending"
    assert MembershipPlan.__table__.c.purchasable.default.arg is False


def test_membership_purchase_and_quota_period_constraints_work_on_sqlite() -> None:
    asyncio.run(_verify_sqlite_invariants())


def test_payment_attempt_records_ten_minute_expiry_and_unique_payment_number() -> None:
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    attempt = MembershipPaymentAttempt(
        membership_purchase_id=str(uuid.uuid4()), payment_no="MPAY123", provider="alipay_sandbox",
        amount=Decimal("19.90"), currency="CNY", qr_code="alipay://qr", expires_at=expiry,
    )

    assert attempt.status == "pending"
    assert attempt.expires_at == expiry
    assert any(
        constraint.name == "uq_membership_payment_attempts_payment_no"
        for constraint in MembershipPaymentAttempt.__table__.constraints
    )
    assert "expired" in str(next(constraint for constraint in MembershipPaymentAttempt.__table__.constraints if constraint.name == "ck_membership_payment_attempts_status").sqltext)


def test_payment_attempt_payment_number_is_unique_and_can_be_current() -> None:
    asyncio.run(_verify_payment_attempt_persistence())


async def _verify_payment_attempt_persistence() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            user = User(id=str(uuid.uuid4()), phone="13800000032")
            plan = MembershipPlan(code="payment-plan", name="Payment plan", duration_days=30, entitlement_codes=[])
            session.add_all([user, plan])
            await session.flush()
            purchase = MembershipPurchase(
                user_id=user.id, membership_plan_id=plan.id, plan_name_snapshot=plan.name,
                amount=Decimal("19.90"), currency="CNY", duration_days=30, generation_quota=10,
                assistant_quota=300, idempotency_key="payment-attempt-key",
            )
            session.add(purchase)
            await session.flush()
            attempt = MembershipPaymentAttempt(
                membership_purchase_id=purchase.id, payment_no="MPAY123", provider="alipay_sandbox",
                amount=purchase.amount, currency=purchase.currency, qr_code="alipay://qr",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
            purchase.current_payment_attempt = attempt
            session.add(attempt)
            await session.flush()
            assert purchase.current_payment_attempt_id == attempt.id

            session.add(MembershipPaymentAttempt(
                membership_purchase_id=purchase.id, payment_no=attempt.payment_no, provider="alipay_sandbox",
                amount=purchase.amount, currency=purchase.currency, qr_code="alipay://another",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            ))
            with pytest.raises(IntegrityError):
                await session.flush()
    finally:
        await engine.dispose()


async def _verify_sqlite_invariants() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            quota_columns = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_columns("ai_quota_periods")
            )
        assert next(column for column in quota_columns if column["name"] == "membership_purchase_id")["nullable"]

        async with session_factory() as session:
            user = User(id=str(uuid.uuid4()), phone="13800000031")
            plan = MembershipPlan(
                code="ai-plan",
                name="AI planning membership",
                duration_days=30,
                entitlement_codes=[],
            )
            session.add_all([user, plan])
            await session.flush()
            purchase = MembershipPurchase(
                user_id=user.id,
                membership_plan_id=plan.id,
                plan_name_snapshot=plan.name,
                amount=Decimal("19.90"),
                currency="CNY",
                duration_days=30,
                generation_quota=10,
                assistant_quota=300,
                idempotency_key="purchase-key",
            )
            session.add(purchase)
            await session.flush()
            assert purchase.status == "pending_payment"
            assert purchase.authorization_status == "pending"

            now = datetime.now(UTC)
            session.add(
                AIQuotaPeriod(
                    user_id=user.id,
                    source_type="membership_purchase",
                    membership_purchase_id=purchase.id,
                    period_start=now,
                    period_end=now + timedelta(days=30),
                    generation_limit=10,
                    generation_used=11,
                    assistant_limit=300,
                    assistant_used=0,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
