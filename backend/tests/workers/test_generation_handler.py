from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.modules.ai_workflows.models import GenerationJob
from app.modules.ai_workflows.workflow import ConstraintViolation, DependencyUnavailable, DraftSchemaError, InsufficientVerifiedCandidates
from app.workers import domain_handlers


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_deterministic_generation_failure_is_terminal_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        job = GenerationJob(
            user_id=str(uuid.uuid4()),
            target_itinerary_id=None,
            idempotency_key="constraint-terminal",
            city_code="330100",
            prompt="Plan a day in Hangzhou",
            start_date=date(2026, 8, 7),
            end_date=date(2026, 8, 7),
            request_json={},
        )
        session.add(job)
        await session.commit()

        class Runtime:
            async def close(self) -> None:
                pass

            def dependencies(self) -> object:
                return object()

            @property
            def workflow_factory(self) -> object:
                return SimpleNamespace(create=lambda _dependencies: SimpleNamespace(
                    run=self._run
                ))

            async def _run(self, _request: object) -> object:
                raise ConstraintViolation(("Budget cannot cover the requested route.",))

        async def open_runtime(_settings: object) -> Runtime:
            return Runtime()

        monkeypatch.setattr(domain_handlers, "open_ai_runtime", open_runtime)
        monkeypatch.setattr(domain_handlers, "Settings", lambda: SimpleNamespace(ai_enabled=True))

        await domain_handlers._run_generation(
            session,
            {
                "trace_id": "a3e6d66e-fd8c-4172-8ac8-9ee6645e9d95",
                "payload": {"generation_job_id": job.id},
            },
        )
        await session.commit()
        await session.refresh(job)
        assert job.status == "succeeded"
        assert job.outcome == "no_result"
        assert job.error_code == "CONSTRAINT_VIOLATION"
        assert job.attempt_count == 1
        assert job.trace_id == "a3e6d66e-fd8c-4172-8ac8-9ee6645e9d95"
    await engine.dispose()


@pytest.mark.anyio
async def test_dependency_failure_releases_job_for_rabbitmq_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        job = GenerationJob(
            user_id=str(uuid.uuid4()),
            target_itinerary_id=None,
            idempotency_key="dependency-retry",
            city_code="330100",
            prompt="Plan a day in Hangzhou",
            start_date=date(2026, 8, 7),
            end_date=date(2026, 8, 7),
            request_json={},
        )
        session.add(job)
        await session.commit()

        class Runtime:
            async def close(self) -> None:
                pass

            def dependencies(self) -> object:
                return object()

            @property
            def workflow_factory(self) -> object:
                return SimpleNamespace(create=lambda _dependencies: SimpleNamespace(
                    run=self._run
                ))

            async def _run(self, _request: object) -> object:
                raise DependencyUnavailable("provider", "provider response detail")

        async def open_runtime(_settings: object) -> Runtime:
            return Runtime()

        monkeypatch.setattr(domain_handlers, "open_ai_runtime", open_runtime)
        monkeypatch.setattr(domain_handlers, "Settings", lambda: SimpleNamespace(ai_enabled=True))

        with pytest.raises(DependencyUnavailable):
            await domain_handlers._run_generation(
                session,
                {
                    "trace_id": "b7e0a089-9866-4c52-b5d2-a35e4bd9d219",
                    "payload": {"generation_job_id": job.id},
                },
            )
        await session.refresh(job)
        assert job.status == "queued"
        assert job.progress == 0
        assert job.attempt_count == 1
        assert job.trace_id == "b7e0a089-9866-4c52-b5d2-a35e4bd9d219"
        assert job.last_error_code == "AI_DEPENDENCY_UNAVAILABLE"
        assert job.last_error_message == "AI planning dependencies are temporarily unavailable."
    await engine.dispose()


@pytest.mark.anyio
async def test_invalid_model_draft_is_terminal_unavailable_not_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        job = GenerationJob(
            user_id=str(uuid.uuid4()),
            target_itinerary_id=None,
            idempotency_key="invalid-draft",
            city_code="330100",
            prompt="Plan a day in Hangzhou",
            start_date=date(2026, 8, 7),
            end_date=date(2026, 8, 7),
            request_json={},
        )
        session.add(job)
        await session.commit()

        class Runtime:
            async def close(self) -> None:
                pass

            def dependencies(self) -> object:
                return object()

            @property
            def workflow_factory(self) -> object:
                return SimpleNamespace(create=lambda _dependencies: SimpleNamespace(run=self._run))

            async def _run(self, _request: object) -> object:
                raise DraftSchemaError("Each activity requires poi_id and title")

        async def open_runtime(_settings: object) -> Runtime:
            return Runtime()

        monkeypatch.setattr(domain_handlers, "open_ai_runtime", open_runtime)
        monkeypatch.setattr(domain_handlers, "Settings", lambda: SimpleNamespace(ai_enabled=True))

        await domain_handlers._run_generation(session, {"payload": {"generation_job_id": job.id}})
        await session.commit()
        await session.refresh(job)
        assert job.status == "failed"
        assert job.outcome == "unavailable"
        assert job.error_code == "INVALID_DRAFT_SCHEMA"
        assert "invalid itinerary draft" in (job.message or "")
    await engine.dispose()


@pytest.mark.anyio
async def test_generation_handler_records_safe_progress_and_maps_insufficient_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        job = GenerationJob(
            user_id=str(uuid.uuid4()), target_itinerary_id=None, idempotency_key="safe-progress",
            city_code="430100", prompt="ignored raw field", start_date=date(2026, 8, 10), end_date=date(2026, 8, 10),
            request_json={"destination": {"name": "Changsha"}, "preference_tags": ["citywalk"], "prompt": "quiet places"},
        )
        session.add(job)
        await session.commit()

        class Runtime:
            async def close(self) -> None:
                pass

            def dependencies(self) -> object:
                return object()

            @property
            def workflow_factory(self) -> object:
                return SimpleNamespace(create=lambda _dependencies: SimpleNamespace(run=self._run))

            async def _run(self, request: object) -> object:
                assert request.prompt == "Changsha citywalk quiet places"
                await request.progress_callback("retrieving_reviewed_sources")
                await request.progress_callback("verifying_pois")
                await request.progress_callback("planning")
                await request.progress_callback("validating")
                raise InsufficientVerifiedCandidates()

        statuses: list[str] = []
        original_mark_progress = domain_handlers.GenerationJobService.mark_progress

        async def mark_progress(self: object, *args: object, **kwargs: object) -> object:
            statuses.append(str(kwargs["status"]))
            return await original_mark_progress(self, *args, **kwargs)

        async def open_runtime(_settings: object) -> Runtime:
            return Runtime()

        monkeypatch.setattr(domain_handlers, "open_ai_runtime", open_runtime)
        monkeypatch.setattr(domain_handlers, "Settings", lambda: SimpleNamespace(ai_enabled=True))
        monkeypatch.setattr(domain_handlers.GenerationJobService, "mark_progress", mark_progress)
        await domain_handlers._run_generation(session, {"trace_id": str(uuid.uuid4()), "payload": {"generation_job_id": job.id}})
        await session.commit()
        await session.refresh(job)

        assert statuses == ["retrieving_reviewed_sources", "verifying_pois", "planning", "validating"]
        assert (job.status, job.outcome, job.error_code, job.message) == (
            "succeeded", "no_result", "INSUFFICIENT_VERIFIED_CANDIDATES", "Not enough verified places were found for this trip.",
        )
    await engine.dispose()


@pytest.mark.anyio
async def test_new_generation_does_not_treat_precreated_itinerary_as_modification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        job = GenerationJob(
            user_id=str(uuid.uuid4()),
            target_itinerary_id=None,
            idempotency_key="new-plan-with-precreated-target",
            city_code="430100",
            prompt="",
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 13),
            request_json={
                "destination": {"name": "长沙市"},
                "preference_tags": ["经典必玩", "吃吃喝喝", "citywalk"],
                "prompt": "",
                "base_version": None,
            },
        )
        session.add(job)
        await session.commit()
        # The service pre-creates this target for applying a future preview.
        job.target_itinerary_id = str(uuid.uuid4())
        await session.commit()

        class Runtime:
            async def close(self) -> None:
                pass

            def dependencies(self) -> object:
                return object()

            @property
            def workflow_factory(self) -> object:
                return SimpleNamespace(create=lambda _dependencies: SimpleNamespace(run=self._run))

            async def _run(self, request: object) -> object:
                assert request.target_itinerary_id is None
                assert request.base_version is None
                assert request.base_snapshot is None
                assert request.workflow_run_id
                raise InsufficientVerifiedCandidates()

        async def open_runtime(_settings: object) -> Runtime:
            return Runtime()

        monkeypatch.setattr(domain_handlers, "open_ai_runtime", open_runtime)
        monkeypatch.setattr(domain_handlers, "Settings", lambda: SimpleNamespace(ai_enabled=True))

        await domain_handlers._run_generation(
            session,
            {"trace_id": str(uuid.uuid4()), "payload": {"generation_job_id": job.id}},
        )
        await session.commit()
        await session.refresh(job)

        assert job.status == "succeeded"
        assert job.error_code == "INSUFFICIENT_VERIFIED_CANDIDATES"
    await engine.dispose()
