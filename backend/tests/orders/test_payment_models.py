import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.modules.orders.models import PaymentCallbackEvent, PaymentRecord


def test_payment_model_metadata_declares_idempotency_and_callback_audit_facts() -> None:
    payment_columns = PaymentRecord.__table__.c
    callback_columns = PaymentCallbackEvent.__table__.c

    assert not payment_columns.idempotency_key.nullable
    assert payment_columns.idempotency_key.type.length == 128
    assert payment_columns.paid_at.nullable
    assert callback_columns.provider_transaction_id.nullable
    assert callback_columns.raw_payload.nullable is False
    assert callback_columns.verification_status.default.arg == "pending"
    assert callback_columns.processing_status.default.arg == "pending"
    assert {constraint.name for constraint in PaymentRecord.__table__.constraints} >= {"uq_payment_records_order_key"}
    assert {constraint.name for constraint in PaymentCallbackEvent.__table__.constraints} >= {
        "uq_payment_callback_provider_tx",
        "ck_payment_callback_events_verification_status",
        "ck_payment_callback_events_processing_status",
    }


def test_payment_idempotency_and_callback_identifier_policy_work_on_sqlite() -> None:
    asyncio.run(_verify_sqlite_invariants())


async def _verify_sqlite_invariants() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            schema = await connection.run_sync(lambda sync_connection: inspect(sync_connection).get_columns("payment_callback_events"))
        assert next(column for column in schema if column["name"] == "provider_transaction_id")["nullable"]

        async with session_factory() as session:
            session.add_all(
                [
                    PaymentRecord(order_id="order-1", idempotency_key="initiation-1", provider="alipay", amount=Decimal("1.00"), currency="CNY"),
                    PaymentRecord(order_id="order-1", idempotency_key="initiation-1", provider="alipay", amount=Decimal("1.00"), currency="CNY"),
                ]
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            session.add_all(
                [
                    PaymentCallbackEvent(provider="alipay", provider_transaction_id=None, raw_payload={}),
                    PaymentCallbackEvent(
                        provider="alipay",
                        provider_transaction_id=None,
                        raw_payload={},
                        verification_status="rejected",
                        verification_error="missing trade_no",
                    ),
                ]
            )
            await session.commit()
    finally:
        await engine.dispose()
