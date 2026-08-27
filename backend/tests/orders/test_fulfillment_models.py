import asyncio

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.modules.orders.models import FulfillmentAttempt


def test_fulfillment_attempt_metadata_declares_durable_confirmation_invariants() -> None:
    columns = FulfillmentAttempt.__table__.c

    assert not columns.order_id.nullable
    assert columns.source.type.length == 64
    assert not columns.idempotency_key.nullable
    assert columns.idempotency_key.type.length == 128
    assert columns.external_confirmation_id.nullable
    assert columns.failure_code.nullable
    assert columns.redacted_result.nullable
    assert "raw_payload" not in columns
    assert columns.attempt_count.default.arg == 0
    assert columns.status.default.arg == "queued"
    assert {constraint.name for constraint in FulfillmentAttempt.__table__.constraints} >= {
        "ck_fulfillment_attempts_status",
        "ck_fulfillment_attempts_attempt_count",
        "uq_fulfillment_attempts_order",
        "uq_fulfillment_attempts_idempotency_key",
    }


def test_fulfillment_attempt_persists_one_request_per_order_on_sqlite() -> None:
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
                    FulfillmentAttempt(order_id="order-1", source="supplier", idempotency_key="fulfillment:order-1"),
                    FulfillmentAttempt(order_id="order-1", source="supplier", idempotency_key="fulfillment:order-1:duplicate"),
                ]
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            session.add_all(
                [
                    FulfillmentAttempt(order_id="order-2", source="supplier", idempotency_key="fulfillment:order-2"),
                    FulfillmentAttempt(
                        order_id="order-3",
                        source="supplier",
                        idempotency_key="fulfillment:order-3",
                        external_confirmation_id="confirmation-1",
                        redacted_result={"status": "confirmed"},
                    ),
                ]
            )
            await session.commit()

            session.add(
                FulfillmentAttempt(
                    order_id="order-4",
                    source="supplier",
                    idempotency_key="fulfillment:order-4",
                    external_confirmation_id="confirmation-1",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
