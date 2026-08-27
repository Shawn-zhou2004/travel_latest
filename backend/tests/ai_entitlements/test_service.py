from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.ai_entitlements.service import AIEntitlementError, AIEntitlementService
from app.modules.membership_purchases.models import AIQuotaPeriod


async def _session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    return session, engine


@pytest.mark.anyio
async def test_free_quota_is_bounded_and_resets_each_calendar_month() -> None:
    session, engine = await _session()
    try:
        user_id = str(uuid4())
        session.add(User(id=user_id, phone="13600000031"))
        await session.commit()
        august = AIEntitlementService(session, now=datetime(2026, 8, 31, 23, 59, tzinfo=UTC))

        consumed = await august.consume(user_id, "itinerary_generation")
        assert consumed.source == "free"
        assert consumed.remaining == 0
        with pytest.raises(AIEntitlementError) as error:
            await august.consume(user_id, "itinerary_generation")
        assert error.value.code == "AI_QUOTA_EXHAUSTED"
        assert error.value.upgrade_available is True

        september = AIEntitlementService(session, now=datetime(2026, 9, 1, tzinfo=UTC))
        assert (await september.consume(user_id, "itinerary_generation")).remaining == 0
        for _ in range(20):
            await september.consume(user_id, "assistant_message")
        with pytest.raises(AIEntitlementError):
            await september.consume(user_id, "assistant_message")
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.anyio
async def test_active_membership_is_preferred_and_its_bounds_are_enforced() -> None:
    session, engine = await _session()
    try:
        user_id = str(uuid4())
        now = datetime(2026, 8, 13, tzinfo=UTC)
        session.add(User(id=user_id, phone="13600000032"))
        session.add(AIQuotaPeriod(
            user_id=user_id,
            source_type="membership_purchase",
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 8, 14, tzinfo=UTC),
            generation_limit=10,
            assistant_limit=300,
        ))
        await session.commit()
        quotas = AIEntitlementService(session, now=now)

        for remaining in range(9, -1, -1):
            result = await quotas.consume(user_id, "itinerary_generation")
            assert result.source == "membership"
            assert result.remaining == remaining
        with pytest.raises(AIEntitlementError) as error:
            await quotas.consume(user_id, "itinerary_generation")
        assert error.value.upgrade_available is False

        free, membership = await quotas.balances(user_id)
        assert free.itinerary_generation_remaining == 1
        assert membership is not None
        assert membership.itinerary_generation_remaining == 0

        at_end = AIEntitlementService(session, now=datetime(2026, 8, 14, tzinfo=UTC))
        assert (await at_end.consume(user_id, "itinerary_generation")).source == "free"
    finally:
        await session.close()
        await engine.dispose()
