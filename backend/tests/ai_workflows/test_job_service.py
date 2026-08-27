from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base, new_uuid
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.ai_workflows.models import GenerationJob
from app.modules.itineraries.models import Itinerary  # noqa: F401
from app.modules.itineraries.models import ItineraryVersion
from app.modules.itineraries.models import ItineraryDay, ItineraryEvent
from app.modules.itineraries.service import ItineraryService
from app.modules.ai_workflows.schemas import GenerationJobCreate, GenerationJobResponse
from app.modules.ai_workflows.service import GenerationJobError, GenerationJobService


DESTINATION = {
    "name": "长沙市",
    "display_address": "中国 · 湖南省 · 长沙市",
    "city_code": "430100",
}


def test_generation_job_accepts_selected_destination_and_three_preferences() -> None:
    body = GenerationJobCreate.model_validate({
        "destination": DESTINATION,
        "start_date": "2026-10-01",
        "end_date": "2026-10-03",
        "preference_tags": ["吃吃喝喝", "citywalk", "历史古建"],
        "prompt": "  有老人同行  ",
    })

    assert body.city_code == "430100"
    assert body.prompt == "有老人同行"


@pytest.mark.parametrize("preference_tags", [
    ["吃吃喝喝", "吃吃喝喝"],
    ["经典必玩", "吃吃喝喝", "小众探索", "拍照出片"],
    ["不在列表中"],
])
def test_generation_job_rejects_invalid_preference_tags(preference_tags: list[str]) -> None:
    with pytest.raises(ValueError):
        GenerationJobCreate.model_validate({
            "destination": DESTINATION,
            "start_date": "2026-10-01",
            "end_date": "2026-10-01",
            "preference_tags": preference_tags,
        })


def test_new_itinerary_request_rejects_past_start_date() -> None:
    past = date.today().toordinal() - 1
    with pytest.raises(ValueError, match="must not be in the past"):
        GenerationJobCreate.model_validate({
            "destination": DESTINATION,
            "start_date": date.fromordinal(past).isoformat(),
            "end_date": date.today().isoformat(),
        })


def test_modification_request_allows_in_progress_itinerary_dates() -> None:
    past = date.today().toordinal() - 3
    body = GenerationJobCreate.model_validate({
        "start_date": date.fromordinal(past).isoformat(),
        "end_date": date.fromordinal(past + 2).isoformat(),
        "target_itinerary_id": "itinerary-1",
        "base_version": 1,
    })
    assert body.start_date < date.today()
    assert body.target_itinerary_id == "itinerary-1"


@pytest.mark.anyio
async def test_generation_job_is_idempotent_and_enqueues_outbox_event() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = User(phone="13600000017")
            session.add(user)
            await session.commit()
            body = GenerationJobCreate(
                destination=DESTINATION,
                prompt="Plan a quiet three-day trip.",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 3),
            )
            service = GenerationJobService(session)
            first = await service.create(user.id, "generation-key", body)
            second = await service.create(user.id, "generation-key", body)
            assert first.id == second.id
            assert first.trace_id is not None
            events = list((await session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == first.id))).all())
            assert len(events) == 1
            assert events[0].event_type == "ai.generation_requested"
            assert events[0].trace_id == first.trace_id
            itinerary = await session.get(Itinerary, first.target_itinerary_id)
            version = await session.scalar(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == first.target_itinerary_id))
            assert itinerary is not None and itinerary.version == 1
            assert version is not None and version.snapshot["days"] == []
            assert first.request_json["destination"] == DESTINATION
            assert first.request_json["city_code"] == "430100"
            assert first.request_json["preference_tags"] == []
            assert first.request_json["pace"] == "balanced"
            assert first.request_json["budget_amount"] is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generation_job_retry_and_unavailable_result() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = User(phone="13600000018")
            session.add(user)
            await session.commit()
            service = GenerationJobService(session)
            job = await service.create(
                user.id,
                "generation-retry-key",
                GenerationJobCreate(
                    destination=DESTINATION,
                    prompt="Plan a museum visit.",
                    start_date=date(2026, 10, 1),
                    end_date=date(2026, 10, 1),
                ),
            )
            await service.mark_unavailable(job.id, "Embedding service unavailable.")
            await session.commit()
            assert job.status == "failed"
            assert job.outcome == "unavailable"
            assert job.finished_at is not None
            assert job.last_error_code == "AI_DEPENDENCY_UNAVAILABLE"
            assert job.last_error_message == "Embedding service unavailable."
            retried = await service.retry(job.id, user.id)
            assert retried is not None
            assert retried.status == "queued"
            assert retried.finished_at is None
            assert retried.attempt_count == 0
            with pytest.raises(GenerationJobError, match="Only failed"):
                await service.retry(job.id, user.id)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generation_job_attempt_metadata_is_durable_and_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = User(phone="13600000019")
            session.add(user)
            await session.commit()
            service = GenerationJobService(session)
            job = await service.create(
                user.id,
                "generation-attempt-key",
                GenerationJobCreate(
                    destination=DESTINATION,
                    prompt="Plan a tea house visit.",
                    start_date=date(2026, 10, 2),
                    end_date=date(2026, 10, 2),
                ),
            )

            trace_id = new_uuid()
            started = await service.start_attempt(job.id, trace_id=trace_id)
            assert started is job
            assert job.attempt_count == 1
            assert job.last_attempt_at is not None
            assert job.trace_id == trace_id
            assert job.status == "understanding"
            await session.commit()
            await session.refresh(job)
            response = GenerationJobResponse.model_validate(job)
            assert response.attempt_count == 1
            assert response.last_attempt_at is not None
            assert response.trace_id == trace_id

            duplicate = await service.start_attempt(job.id, trace_id=new_uuid())
            assert duplicate is None
            assert job.attempt_count == 1
            assert job.trace_id == trace_id

            await service.mark_no_result(job.id, " NO_TRUSTED_CONTEXT ", "No trusted\ncontext was found.")
            await session.commit()
            await session.refresh(job)
            assert job.last_error_code == "NO_TRUSTED_CONTEXT"
            assert job.last_error_message == "No trusted context was found."
            assert job.finished_at is not None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_targeted_generation_captures_full_base_snapshot_and_requires_current_range() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = User(phone="13600000020")
            session.add(user)
            await session.commit()
            itinerary = await ItineraryService(session).create_itinerary(
                user.id, title="Existing", start_date=date(2026, 10, 1), end_date=date(2026, 10, 2)
            )
            day = ItineraryDay(itinerary_id=itinerary.id, day_date=date(2026, 10, 1), display_order=0)
            session.add(day)
            await session.flush()
            session.add(ItineraryEvent(day_id=day.id, poi_id="poi-1", poi_snapshot={"name": "Museum", "location": {"longitude": 1, "latitude": 2}}, display_order=0))
            await session.commit()
            version = await session.scalar(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id, ItineraryVersion.version == 1))
            assert version is not None
            version.snapshot = await ItineraryService(session).get_snapshot(itinerary)
            await session.commit()
            body = GenerationJobCreate(destination=DESTINATION, prompt="Move the museum", start_date=date(2026, 10, 1), end_date=date(2026, 10, 2), target_itinerary_id=itinerary.id, base_version=1)
            job = await GenerationJobService(session).create(user.id, "modify-1", body)
            assert job.request_json["base_snapshot"]["days"][0]["events"][0]["poi_id"] == "poi-1"
            with pytest.raises(GenerationJobError, match="date range"):
                await GenerationJobService(session).create(user.id, "modify-2", body.model_copy(update={"end_date": date(2026, 10, 3)}))
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_generation_job_progress_is_owned_by_the_active_worker_attempt() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = User(phone="13600000021")
            session.add(user)
            await session.commit()
            service = GenerationJobService(session)
            job = await service.create(
                user.id,
                "generation-progress-key",
                GenerationJobCreate(
                    destination=DESTINATION,
                    start_date=date(2026, 10, 1),
                    end_date=date(2026, 10, 1),
                ),
            )
            trace_id = new_uuid()
            started = await service.start_attempt(job.id, trace_id=trace_id)
            assert started is job

            progressed = await service.mark_progress(
                job.id,
                status="searching_live_sources",
                progress=45,
                trace_id=trace_id,
            )
            assert progressed is job
            await session.commit()
            await session.refresh(job)
            assert (job.status, job.progress) == ("searching_live_sources", 45)

            assert await service.mark_progress(
                job.id,
                status="planning",
                progress=60,
                trace_id=new_uuid(),
            ) is None
            await service.mark_no_result(job.id, "NO_RESULT", "No result.")
            assert await service.mark_progress(
                job.id,
                status="planning",
                progress=60,
                trace_id=trace_id,
            ) is None
            assert job.status == "succeeded"
            assert job.outcome == "no_result"
    finally:
        await engine.dispose()
