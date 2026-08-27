import asyncio
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.community.models import CompanionRequest, Post
from app.modules.itineraries.models import (
    Itinerary,
    ItineraryCopyOperation,
    ItineraryDay,
    ItineraryEvent,
    ItineraryVersion,
    RouteCalculationJob,
    RouteSegment,
    TripCollaborator,
    TripOperation,
    TripShareToken,
)
from app.modules.itineraries.service import ItineraryError, ItineraryService


async def make_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return AsyncSession(engine, expire_on_commit=False), engine


async def make_aggregate(session: AsyncSession) -> tuple[Itinerary, User, User, Post]:
    owner, editor, author = User(phone="13600000011"), User(phone="13600000012"), User(phone="13600000013")
    session.add_all((owner, editor, author))
    await session.flush()
    itinerary = Itinerary(owner_id=owner.id, title="Hangzhou three-day trip", start_date=date(2026, 10, 1), end_date=date(2026, 10, 3))
    session.add(itinerary)
    await session.flush()
    days = [
        ItineraryDay(itinerary_id=itinerary.id, day_date=date(2026, 10, order + 1), display_order=order)
        for order in range(3)
    ]
    session.add_all(days)
    await session.flush()
    version = ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={"title": itinerary.title, "days": []})
    session.add_all([
        ItineraryEvent(day_id=days[0].id, poi_id="poi-1", poi_snapshot={"name": "湖"}, display_order=0),
        RouteSegment(day_id=days[0].id, display_order=0, travel_mode="walking"),
        RouteCalculationJob(itinerary_id=itinerary.id, day_id=days[0].id, requested_by=owner.id, event_ids=[], status="queued"),
        TripCollaborator(itinerary_id=itinerary.id, user_id=editor.id, role="editor", status="accepted"),
        TripShareToken(itinerary_id=itinerary.id, token_hash="token-hash"),
        TripOperation(itinerary_id=itinerary.id, operation_id="old-operation", actor_id=owner.id, operation_type="add_day", base_version=1, result_version=1, result_snapshot={}),
        version,
    ])
    post = Post(
        author_id=author.id,
        content_type="itinerary",
        title="Field note snapshot",
        status="published",
        itinerary_id=itinerary.id,
        itinerary_version_id=version.id,
        itinerary_snapshot_json={"title": itinerary.title, "days": [{"day_date": "2026-10-01"}]},
    )
    session.add(post)
    await session.commit()
    return itinerary, owner, editor, post


def test_owner_delete_removes_aggregate_and_preserves_field_note_snapshot() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner, _, post = await make_aggregate(session)
            await ItineraryService(session).delete_itinerary(itinerary.id, owner.id)
            assert await session.get(Itinerary, itinerary.id) is None
            assert await session.scalar(select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id)) is None
            assert await session.scalar(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id)) is None
            assert await session.scalar(select(ItineraryEvent)) is None
            assert await session.scalar(select(RouteSegment)) is None
            assert await session.scalar(select(RouteCalculationJob)) is None
            assert await session.scalar(select(TripCollaborator)) is None
            assert await session.scalar(select(TripShareToken)) is None
            assert await session.scalar(select(TripOperation)) is None
            preserved = await session.get(Post, post.id)
            assert preserved is not None
            assert preserved.itinerary_id is None
            assert preserved.itinerary_version_id is None
            assert preserved.itinerary_snapshot_json == {"title": itinerary.title, "days": [{"day_date": "2026-10-01"}]}
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_non_owner_delete_leaves_rows_unchanged() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, _, editor, _ = await make_aggregate(session)
            itinerary_id = itinerary.id
            with pytest.raises(ItineraryError) as error:
                await ItineraryService(session).delete_itinerary(itinerary_id, editor.id)
            assert error.value.code == "FORBIDDEN"
            await session.rollback()
            assert await session.get(Itinerary, itinerary_id) is not None
            assert await session.scalar(select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary_id)) is not None
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["open", "full", "closed"])
def test_owner_delete_is_blocked_by_active_companion_plan(status: str) -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner, _, _ = await make_aggregate(session)
            itinerary_id = itinerary.id
            owner_id = owner.id
            session.add(CompanionRequest(
                owner_id=owner_id, itinerary_id=itinerary_id, title="Companion plan", description="Details",
                status=status, accepted_count=1,
            ))
            await session.commit()
            with pytest.raises(ItineraryError, match="active companion") as error:
                await ItineraryService(session).delete_itinerary(itinerary_id, owner_id)
            assert error.value.code == "COMPANION_PLAN_ACTIVE"
            await session.rollback()
            assert await session.get(Itinerary, itinerary_id) is not None
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_remove_day_cleans_day_rows_reorders_and_is_idempotent() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner, _, _ = await make_aggregate(session)
            day = await session.scalar(select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id, ItineraryDay.display_order == 0))
            assert day is not None
            service = ItineraryService(session)
            result = await service.apply_operation(
                itinerary.id, owner.id, base_version=1, operation_id="remove-day", operation_type="remove_day", payload={"day_id": day.id}
            )
            assert result.code == "APPLIED" and result.current_version == 2
            assert result.snapshot is not None
            assert [item["display_order"] for item in result.snapshot["days"]] == [0, 1]
            assert [item["day_date"] for item in result.snapshot["days"]] == ["2026-10-02", "2026-10-03"]
            assert await session.scalar(select(RouteSegment).where(RouteSegment.day_id == day.id)) is None
            assert await session.scalar(select(RouteCalculationJob).where(RouteCalculationJob.day_id == day.id)) is None
            replay = await service.apply_operation(
                itinerary.id, owner.id, base_version=1, operation_id="remove-day", operation_type="remove_day", payload={"day_id": day.id}
            )
            assert replay.idempotent is True and replay.current_version == 2

            remaining_days = list((await session.scalars(select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id))).all())
            for remaining in remaining_days[:-1]:
                next_result = await service.apply_operation(
                    itinerary.id, owner.id, base_version=itinerary.version, operation_id=f"remove-{remaining.id}", operation_type="remove_day", payload={"day_id": remaining.id}
                )
                itinerary.version = next_result.current_version
            current_range_before_last = (itinerary.start_date, itinerary.end_date)
            last_day = await session.scalar(select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id))
            assert last_day is not None
            next_result = await service.apply_operation(
                itinerary.id, owner.id, base_version=itinerary.version, operation_id="remove-last-day", operation_type="remove_day", payload={"day_id": last_day.id}
            )
            itinerary.version = next_result.current_version
            assert await session.scalar(select(func.count(ItineraryDay.id)).where(ItineraryDay.itinerary_id == itinerary.id)) == 0
            assert (itinerary.start_date, itinerary.end_date) == current_range_before_last
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())
