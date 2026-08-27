import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.community.models import CompanionRequest
from app.modules.community.service import CommunityError, CommunityService


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as value:
        yield value
    await engine.dispose()


async def _plan(session, owner, *, status="open", review_status="approved", party_size=3, accepted_count=2):
    plan = CompanionRequest(
        owner_id=owner.id, title="West Lake walk", city_code="330100", description="Original intro",
        trip_kind="trip", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1), party_size=party_size,
        accepted_count=accepted_count, budget_min=600, budget_max=900, currency="CNY", travel_pace="slow",
        interest_tags=["citywalk"], intro_text="Original intro", review_status=review_status, status=status,
    )
    session.add(plan)
    await session.commit()
    return plan


@pytest.mark.anyio
async def test_owner_edits_public_plan_metadata_and_capacity_derives_status(session):
    owner = User(id=str(uuid.uuid4()), phone="13700000051")
    session.add(owner)
    await session.flush()
    plan = await _plan(session, owner, status="full", party_size=2, accepted_count=2)

    updated = await CommunityService(session).update_companion_request(
        plan.id, owner.id, title="Updated walk", city_code="310000", party_size=4, budget_min=800,
        budget_max=1200, currency="CNY", travel_pace="packed", interest_tags=["food", "nightlife"],
        intro_text="Updated public intro.",
    )

    assert updated.title == "Updated walk" and updated.city_code == "310000"
    assert updated.party_size == 4 and updated.status == "open"
    assert updated.budget_min == 800 and updated.budget_max == 1200 and updated.currency == "CNY"
    assert updated.travel_pace == "packed" and updated.interest_tags == ["food", "nightlife"]
    assert updated.intro_text == "Updated public intro."
    await CommunityService(session).update_companion_request(plan.id, owner.id, party_size=2)
    assert plan.status == "full"


@pytest.mark.anyio
async def test_owner_edit_rejects_invalid_capacity_budget_and_terminal_plans(session):
    owner = User(id=str(uuid.uuid4()), phone="13700000052")
    session.add(owner)
    await session.flush()
    plan = await _plan(session, owner)
    service = CommunityService(session)

    with pytest.raises(CommunityError, match="INVALID_COMPANION_CAPACITY"):
        await service.update_companion_request(plan.id, owner.id, party_size=1)
    with pytest.raises(CommunityError, match="INVALID_COMPANION_BUDGET"):
        await service.update_companion_request(plan.id, owner.id, budget_min=100)
    plan.status = "completed"
    with pytest.raises(CommunityError, match="INVALID_COMPANION_REQUEST_TRANSITION"):
        await service.update_companion_request(plan.id, owner.id, intro_text="No changes allowed.")


@pytest.mark.anyio
async def test_expanding_full_unapproved_plan_does_not_bypass_review(session):
    owner = User(id=str(uuid.uuid4()), phone="13700000053")
    session.add(owner)
    await session.flush()
    plan = await _plan(session, owner, status="full", review_status="pending_review", party_size=2, accepted_count=2)

    await CommunityService(session).update_companion_request(plan.id, owner.id, party_size=3)

    assert plan.status == "full"
