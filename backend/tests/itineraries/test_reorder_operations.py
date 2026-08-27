import asyncio
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.itineraries.models import ItineraryDay, ItineraryEvent
from app.modules.itineraries.service import ItineraryService


def test_reorder_event_swaps_adjacent_display_order() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            owner = User(phone="13500000000")
            session.add(owner)
            await session.flush()
            itinerary = await ItineraryService(session).create_itinerary(
                owner.id, title="Reorder", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1)
            )
            day = ItineraryDay(itinerary_id=itinerary.id, day_date=date(2026, 10, 1), display_order=0)
            session.add(day)
            await session.flush()
            first = ItineraryEvent(day_id=day.id, poi_id="poi-a", poi_snapshot={"name": "First"}, display_order=0)
            second = ItineraryEvent(day_id=day.id, poi_id="poi-b", poi_snapshot={"name": "Second"}, display_order=1)
            session.add_all([first, second])
            await session.commit()
            result = await ItineraryService(session).apply_operation(
                itinerary.id,
                owner.id,
                base_version=1,
                operation_id="reorder-1",
                operation_type="reorder_event",
                payload={"event_id": second.id, "direction": "up"},
            )
            assert result.code == "APPLIED"
            orders = list((await session.scalars(select(ItineraryEvent).where(ItineraryEvent.day_id == day.id).order_by(ItineraryEvent.display_order))).all())
            assert [item.poi_id for item in orders] == ["poi-b", "poi-a"]
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())
