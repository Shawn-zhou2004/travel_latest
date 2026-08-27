import asyncio
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.base import Base, new_uuid
from app.models.user import User
from app.modules.itineraries.models import ItineraryDay, ItineraryEvent, ItineraryVersion, RouteSegment, TripCollaborator, TripOperation
from app.modules.itineraries.service import ItineraryService
from app.modules.maps.service import MapPOI, MapRoute


async def make_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    return session, engine


async def make_itinerary(session: AsyncSession):
    owner = User(phone="13800000000")
    session.add(owner)
    await session.commit()
    itinerary = await ItineraryService(session).create_itinerary(
        owner.id, title="Hangzhou", start_date=date(2026, 10, 1), end_date=date(2026, 10, 2)
    )
    return itinerary, owner


def test_operation_rejects_stale_base_version() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            result = await ItineraryService(session).apply_operation(
                itinerary.id, owner.id, base_version=0, operation_id="op-1", operation_type="add_day", payload={"day_date": "2026-10-01"}
            )
            assert result.code == "VERSION_CONFLICT"
            assert result.current_version == itinerary.version
        finally:
            await session.close()
            await engine.dispose()
    asyncio.run(scenario())


def test_operation_is_idempotent_and_records_one_version() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            service = ItineraryService(session)
            first = await service.apply_operation(itinerary.id, owner.id, base_version=1, operation_id="op-1", operation_type="add_day", payload={"day_date": "2026-10-01"})
            second = await service.apply_operation(itinerary.id, owner.id, base_version=1, operation_id="op-1", operation_type="add_day", payload={"day_date": "2026-10-01"})
            assert first.code == "APPLIED"
            assert second.idempotent is True
            assert second.current_version == 2
            assert len(list((await session.scalars(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id))).all())) == 2
            assert len(list((await session.scalars(select(TripOperation).where(TripOperation.itinerary_id == itinerary.id))).all())) == 1
        finally:
            await session.close()
            await engine.dispose()
    asyncio.run(scenario())


def test_add_day_extends_the_itinerary_range_for_any_selected_date() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            result = await ItineraryService(session).apply_operation(
                itinerary.id, owner.id, base_version=1, operation_id="day-later", operation_type="add_day",
                payload={"day_date": "2026-10-10"},
            )
            assert result.code == "APPLIED"
            assert result.snapshot is not None
            assert result.snapshot["end_date"] == "2026-10-10"
            assert result.snapshot["days"][0]["day_date"] == "2026-10-10"
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_ai_preview_modifies_one_activity_and_preserves_unrelated_days() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            service = ItineraryService(session)
            first = await service.apply_operation(
                itinerary.id, owner.id, base_version=1, operation_id="day-1", operation_type="add_day", payload={"day_date": "2026-10-01"}
            )
            second = await service.apply_operation(
                itinerary.id, owner.id, base_version=2, operation_id="day-2", operation_type="add_day", payload={"day_date": "2026-10-02"}
            )
            preview = {
                "title": "Updated",
                "days": [
                    {"date": "2026-10-01", "activities": [{"poi_id": "POI-NEW", "poi_name": "New place", "longitude": 120.1, "latitude": 30.2, "title": "Changed"}]},
                    {"date": "2026-10-02", "activities": [{"poi_id": "POI-KEEP", "poi_name": "Kept place", "longitude": 120.2, "latitude": 30.3, "title": "Unrelated"}]},
                ],
            }
            result = await service.apply_operation(itinerary.id, owner.id, base_version=3, operation_id="ai-1", operation_type="apply_ai_preview", payload={"draft": preview, "base_version": 3})
            assert result.code == "APPLIED"
            snapshot = await service.get_snapshot(itinerary)
            assert [day["day_date"] for day in snapshot["days"]] == ["2026-10-01", "2026-10-02"]
            assert snapshot["days"][0]["events"][0]["poi_id"] == "POI-NEW"
            assert snapshot["days"][1]["events"][0]["poi_id"] == "POI-KEEP"
            stale = await service.apply_operation(itinerary.id, owner.id, base_version=3, operation_id="ai-stale", operation_type="apply_ai_preview", payload={"draft": preview, "base_version": 3})
            assert stale.code == "VERSION_CONFLICT"
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_ai_preview_preserves_an_unplanned_day_without_queuing_a_route() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            service = ItineraryService(session)
            preview = {
                "title": "Updated",
                "days": [
                    {"date": "2026-10-01", "activities": [{"poi_id": "POI-NEW", "poi_name": "New place", "longitude": 120.1, "latitude": 30.2, "title": "Changed"}]},
                    {"date": "2026-10-02", "activities": []},
                ],
            }

            result = await service.apply_operation(itinerary.id, owner.id, base_version=1, operation_id="ai-empty-day", operation_type="apply_ai_preview", payload={"draft": preview, "base_version": 1})

            assert result.code == "APPLIED"
            assert result.snapshot is not None
            assert [len(day["events"]) for day in result.snapshot["days"]] == [1, 0]
            assert len(list((await session.scalars(select(RouteSegment))).all())) == 0
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_authorized_readers_can_list_versions_and_read_a_snapshot() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            collaborator = User(phone="13900000000")
            outsider = User(phone="13700000000")
            session.add_all((collaborator, outsider))
            await session.commit()
            service = ItineraryService(session)
            await service.apply_operation(
                itinerary.id, owner.id, base_version=1, operation_id="day-1", operation_type="add_day", payload={"day_date": "2026-10-01"}
            )
            session.add(TripCollaborator(itinerary_id=itinerary.id, user_id=collaborator.id, role="viewer", status="accepted"))
            await session.commit()

            versions = await service.list_versions(itinerary.id, collaborator.id)
            assert versions is not None
            assert [version["version_no"] for version in versions] == [2, 1]
            assert versions[0]["source"] == "add_day"
            assert "snapshot" not in versions[0]

            detail = await service.get_version(itinerary.id, 2, collaborator.id)
            assert detail is not None
            assert detail["snapshot"]["days"][0]["day_date"] == "2026-10-01"
            assert await service.list_versions(itinerary.id, outsider.id) is None
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_only_accepted_editor_can_mutate() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            collaborator = User(phone="13900000000")
            session.add(collaborator)
            await session.commit()
            service = ItineraryService(session)
            denied = await service.apply_operation(itinerary.id, collaborator.id, base_version=1, operation_id="op-1", operation_type="add_day", payload={"day_date": "2026-10-01"})
            assert denied.code == "FORBIDDEN"
            session.add(TripCollaborator(itinerary_id=itinerary.id, user_id=collaborator.id, role="editor", status="accepted"))
            await session.commit()
            allowed = await service.apply_operation(itinerary.id, collaborator.id, base_version=1, operation_id="op-2", operation_type="add_day", payload={"day_date": "2026-10-01"})
            assert allowed.code == "APPLIED"
        finally:
            await session.close()
            await engine.dispose()
    asyncio.run(scenario())


def test_add_event_persists_the_verified_poi_snapshot() -> None:
    class VerifiedMapService:
        async def verify_poi(self, poi_id: str) -> MapPOI:
            assert poi_id == "B001"
            return MapPOI("B001", "西湖", "杭州市西湖区", (120.1302, 30.24), city="杭州市", type_name="风景名胜")

    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            service = ItineraryService(session, VerifiedMapService())
            day_result = await service.apply_operation(
                itinerary.id, owner.id, base_version=1, operation_id="day-1", operation_type="add_day", payload={"day_date": "2026-10-01"}
            )
            day_id = day_result.snapshot["days"][0]["id"]
            result = await service.apply_operation(
                itinerary.id, owner.id, base_version=2, operation_id="event-1", operation_type="add_event", payload={"day_id": day_id, "poi_id": "B001"}
            )
            assert result.code == "APPLIED"
            event = await session.scalar(select(ItineraryEvent).where(ItineraryEvent.day_id == day_id))
            assert event is not None
            assert event.poi_snapshot["name"] == "西湖"
            assert event.poi_snapshot["location"] == {"longitude": 120.1302, "latitude": 30.24}
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_day_order_constraint_rejects_duplicate_display_order() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, _ = await make_itinerary(session)
            session.add_all([
                ItineraryDay(itinerary_id=itinerary.id, day_date=date(2026, 10, 1), display_order=0),
                ItineraryDay(itinerary_id=itinerary.id, day_date=date(2026, 10, 2), display_order=0),
            ])
            with pytest.raises(Exception):
                await session.commit()
        finally:
            await session.close()
            await engine.dispose()
    asyncio.run(scenario())


def test_recalculate_route_queues_a_job_then_worker_persists_route_segments() -> None:
    class RoutedMapService:
        async def verify_poi(self, poi_id: str) -> MapPOI:
            return MapPOI(poi_id, poi_id, "Hangzhou", (120.1 if poi_id == "B001" else 120.2, 30.2), city="Hangzhou")

        async def plan_driving_route(self, origin: tuple[float, float], destination: tuple[float, float]) -> MapRoute:
            assert origin == (120.1, 30.2)
            assert destination == (120.2, 30.2)
            return MapRoute(1200, 300, (origin, (120.15, 30.21), destination))

    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner = await make_itinerary(session)
            service = ItineraryService(session, RoutedMapService())
            day = await service.apply_operation(
                itinerary.id, owner.id, base_version=1, operation_id="day-1", operation_type="add_day", payload={"day_date": "2026-10-01"}
            )
            day_id = day.snapshot["days"][0]["id"]
            first = await service.apply_operation(
                itinerary.id, owner.id, base_version=2, operation_id="event-1", operation_type="add_event", payload={"day_id": day_id, "poi_id": "B001"}
            )
            second = await service.apply_operation(
                itinerary.id, owner.id, base_version=3, operation_id="event-2", operation_type="add_event", payload={"day_id": day_id, "poi_id": "B002"}
            )
            result = await service.apply_operation(
                itinerary.id, owner.id, base_version=4, operation_id="route-1", operation_type="recalculate_route", payload={"day_id": day_id}
            )
            assert first.code == second.code == result.code == "APPLIED"
            assert result.route_job is not None
            assert result.route_job.status == "queued"
            assert await session.scalar(select(RouteSegment).where(RouteSegment.day_id == day_id)) is None
            await service.process_route_calculation(result.route_job.id)
            await session.commit()
            segment = await session.scalar(select(RouteSegment).where(RouteSegment.day_id == day_id))
            assert segment is not None
            assert segment.distance_meters == 1200
            snapshot = await service.get_snapshot(itinerary)
            assert snapshot["days"][0]["route_segments"][0]["route_snapshot"]["polyline"][1] == {"longitude": 120.15, "latitude": 30.21}
            assert snapshot["days"][0]["route_calculation"]["status"] == "completed"
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_public_ids_are_uuid_v4() -> None:
    assert new_uuid().count("-") == 4
    with pytest.raises(ValueError):
        User(id="not-a-uuid", phone="13700000000")
