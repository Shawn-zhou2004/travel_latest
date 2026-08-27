import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.chat.models import Conversation  # noqa: F401
from app.modules.community.models import CompanionApplication, CompanionRequest
from app.modules.itineraries.models import Itinerary
from app.modules.media.models import MediaAsset  # noqa: F401


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as value:
        yield value
    await engine.dispose()


@pytest.mark.anyio
async def test_companion_plan_allows_legacy_requests_and_nullable_conversation_links(session):
    owner = User(id=str(uuid.uuid4()), phone="13800000101")
    legacy = CompanionRequest(owner_id=owner.id, title="Legacy", description="Existing request")
    session.add_all([owner, legacy])
    await session.commit()

    assert legacy.accepted_count == 1
    assert legacy.itinerary_id is None
    application = CompanionApplication(request_id=legacy.id, applicant_id=owner.id)
    session.add(application)
    await session.commit()
    assert application.conversation_id is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"accepted_count": 3}, "accepted_count"),
        ({"party_size": 1, "accepted_count": 1}, "party_size"),
        ({"status": "pending"}, "status"),
        ({"start_date": date(2026, 10, 3), "end_date": date(2026, 10, 2)}, "date_order"),
        ({"budget_min": Decimal("900"), "budget_max": Decimal("600")}, "budget_order"),
        ({"trip_kind": "weekend"}, "trip_kind"),
        ({"travel_pace": "fast"}, "travel_pace"),
    ],
)
async def test_companion_plan_requires_valid_capacity_and_business_status(session, overrides, constraint):
    owner = User(id=str(uuid.uuid4()), phone=f"13800000{uuid.uuid4().int % 10_000:04d}")
    itinerary = Itinerary(
        owner_id=owner.id,
        title="Hangzhou walk",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 2),
    )
    session.add_all([owner, itinerary])
    await session.flush()
    values = {
        "owner_id": owner.id,
        "title": "Hangzhou walk",
        "description": "Slow route",
        "itinerary_id": itinerary.id,
        "trip_kind": "trip",
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 10, 2),
        "party_size": 2,
        "accepted_count": 2,
        "budget_min": Decimal("600"),
        "budget_max": Decimal("900"),
        "travel_pace": "slow",
        "interest_tags": ["citywalk"],
        "intro_text": "Walk and take photos.",
        "status": "open",
    }
    request = CompanionRequest(**(values | overrides))
    session.add(request)
    with pytest.raises(IntegrityError, match=constraint):
        await session.commit()
