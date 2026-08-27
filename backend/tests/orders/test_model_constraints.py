import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.orders.models import TravelOffer, TravelSearchJob
from app.modules.orders.services import DomainError, OrderService


def test_offer_is_immutable_after_insert() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(phone="13800000000")
            session.add(user)
            await session.flush()
            job = TravelSearchJob(user_id=user.id, idempotency_key="search-1", search_type="hotel", query_snapshot={}, status="empty", source="test")
            session.add(job)
            await session.flush()
            offer = TravelOffer(search_job_id=job.id, source="test", external_offer_id="o1", title="Room", amount=Decimal("10.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) + timedelta(minutes=5), change_rules={}, snapshot={})
            session.add(offer)
            await session.commit()
            with pytest.raises(ValueError, match="immutable"):
                offer.title = "Changed"
        await engine.dispose()
    asyncio.run(scenario())


def test_expired_offer_cannot_create_order() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(phone="13900000000")
            session.add(user)
            await session.flush()
            job = TravelSearchJob(user_id=user.id, idempotency_key="search-2", search_type="hotel", query_snapshot={}, status="empty", source="test")
            session.add(job)
            await session.flush()
            offer = TravelOffer(search_job_id=job.id, source="test", external_offer_id="o2", title="Expired room", amount=Decimal("10.00"), currency="CNY", availability="available", valid_until=datetime.now(UTC) - timedelta(seconds=1), change_rules={}, snapshot={})
            session.add(offer)
            await session.commit()
            with pytest.raises(DomainError, match="expired") as error:
                await OrderService(session).create_from_offer(user.id, offer.id, "order-1")
            assert error.value.code == "OFFER_EXPIRED"
        await engine.dispose()
    asyncio.run(scenario())
