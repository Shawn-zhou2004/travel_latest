import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.modules.orders.models import RefundRecord


def test_refund_metadata_declares_request_facts_and_idempotency() -> None:
    columns = RefundRecord.__table__.c

    assert not columns.payment_id.nullable
    assert not columns.idempotency_key.nullable
    assert columns.idempotency_key.type.length == 128
    assert not columns.currency.nullable
    assert columns.currency.type.length == 3
    assert not columns.reason.nullable
    assert columns.reason.type.length == 500
    assert not columns.requested_by.nullable
    assert not columns.requested_at.nullable
    assert columns.requested_at.default.arg is not None
    assert columns.completed_at.nullable
    assert columns.failure_code.nullable
    assert columns.failure_code.type.length == 64
    assert {constraint.name for constraint in RefundRecord.__table__.constraints} >= {
        "uq_refund_records_payment_key",
    }


def test_refund_idempotency_is_scoped_to_payment_on_sqlite() -> None:
    asyncio.run(_verify_sqlite_invariants())


async def _verify_sqlite_invariants() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            session.add_all(
                [
                    RefundRecord(
                        payment_id="payment-1",
                        idempotency_key="refund-1",
                        amount=Decimal("188.00"),
                        currency="CNY",
                        reason="supplier_unavailable",
                        requested_by="user-1",
                    ),
                    RefundRecord(
                        payment_id="payment-1",
                        idempotency_key="refund-1",
                        amount=Decimal("188.00"),
                        currency="CNY",
                        reason="supplier_unavailable",
                        requested_by="user-1",
                    ),
                ]
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            completed_at = datetime.now(UTC)
            session.add_all(
                [
                    RefundRecord(
                        payment_id="payment-1",
                        idempotency_key="refund-1",
                        amount=Decimal("188.00"),
                        currency="CNY",
                        reason="supplier_unavailable",
                        requested_by="user-1",
                    ),
                    RefundRecord(
                        payment_id="payment-2",
                        idempotency_key="refund-1",
                        amount=Decimal("188.00"),
                        currency="CNY",
                        reason="supplier_unavailable",
                        requested_by="user-1",
                        status="failed",
                        completed_at=completed_at,
                        failure_code="provider_rejected",
                    ),
                ]
            )
            await session.commit()
    finally:
        await engine.dispose()
