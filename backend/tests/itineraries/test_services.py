import asyncio
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.community.models import Post
from app.modules.itineraries.models import ItineraryCopyOperation, ItineraryDay, ItineraryEvent, ItineraryVersion
from app.modules.itineraries.service import ItineraryService


def test_create_manual_plan_creates_all_dates_without_events() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            user = User(phone="13600000001")
            session.add(user)
            await session.commit()

            service = ItineraryService(session)
            itinerary = await service.create_manual_plan(
                user.id,
                title="长沙三日游",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 3),
                destination={"name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100"},
            )

            snapshot = await service.get_snapshot(itinerary)
            assert [day["day_date"] for day in snapshot["days"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
            assert all(day["events"] == [] for day in snapshot["days"])
            version = await session.scalar(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id))
            assert version is not None
            assert version.version == 1
            assert version.snapshot["destination"] == {
                "name": "长沙市", "display_address": "中国 · 湖南省 · 长沙市", "city_code": "430100",
            }
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_copy_field_note_materializes_fresh_owned_aggregate_once() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            author, reader = User(phone="13600000002"), User(phone="13600000007")
            session.add_all([author, reader])
            await session.flush()
            snapshot = {
                "title": "Frozen route", "start_date": "2026-10-01", "end_date": "2026-10-02",
                "days": [
                    {"day_date": "2026-10-01", "display_order": 0, "events": [{"poi_id": "poi-1", "poi_snapshot": {"name": "Lake"}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": "Morning"}]},
                    {"day_date": "2026-10-02", "display_order": 1, "events": [{"poi_id": "poi-2", "poi_snapshot": {"name": "Garden"}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": None}]},
                ],
            }
            post = Post(author_id=author.id, content_type="itinerary", title="Field note", status="published", itinerary_snapshot_json=snapshot, copy_count=0)
            session.add(post)
            await session.commit()

            service = ItineraryService(session)
            first = await service.copy_field_note(post, reader.id, "copy-key-1")
            second = await service.copy_field_note(post, reader.id, "copy-key-1")
            assert first.itinerary.id == second.itinerary.id
            assert first.idempotent is False and second.idempotent is True
            assert first.itinerary.owner_id == reader.id and first.itinerary.source_post_id == post.id
            days = list((await session.scalars(__import__("sqlalchemy").select(ItineraryDay).where(ItineraryDay.itinerary_id == first.itinerary.id))).all())
            events = list((await session.scalars(__import__("sqlalchemy").select(ItineraryEvent).where(ItineraryEvent.day_id.in_([day.id for day in days])))).all())
            assert len(days) == 2 and len(events) == 2
            operation_count = await session.scalar(__import__("sqlalchemy").select(__import__("sqlalchemy").func.count(ItineraryCopyOperation.id)).where(ItineraryCopyOperation.source_post_id == post.id))
            await session.refresh(post)
            assert operation_count == 1 and post.copy_count == 1
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())
