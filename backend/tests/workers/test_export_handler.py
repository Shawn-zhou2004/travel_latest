from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.integrations.object_storage import StorageUnavailable
from app.modules.exports.models import ExportTask
from app.modules.itineraries.models import Itinerary, ItineraryVersion
from app.workers import domain_handlers


class FakeStorage:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def upload_bytes(self, *, key: str, data: bytes, mime_type: str, sha256: str) -> str:
        assert key.startswith("exports/")
        assert data.startswith(b"PK")
        return "fake-etag"


class UnavailableStorage:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def upload_bytes(self, **_kwargs: object) -> str:
        raise StorageUnavailable("unavailable")


@pytest.mark.anyio
async def test_export_handler_claims_attempt_and_completes_private_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    requester_id, itinerary_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session:
        session.add_all((
            User(id=requester_id, phone=f"1{uuid.uuid4().int % 10**10:010d}"),
            Itinerary(id=itinerary_id, owner_id=requester_id, title="Trip", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7)),
        ))
        version = ItineraryVersion(itinerary_id=itinerary_id, version=1, created_by=requester_id, snapshot={"title": "Trip", "days": []})
        session.add(version)
        await session.flush()
        task = ExportTask(requester_id=requester_id, itinerary_id=itinerary_id, itinerary_version_id=version.id, version_no=1, idempotency_key="worker-key", snapshot_json={"title": "Trip", "days": []})
        session.add(task)
        await session.commit()
        monkeypatch.setattr(domain_handlers, "S3ObjectStorage", FakeStorage)
        await domain_handlers._run_export(session, {"trace_id": str(uuid.uuid4()), "payload": {"export_task_id": task.id}})
        await session.commit()
        await session.refresh(task)
        assert task.status == "succeeded"
        assert task.progress == 100
        assert task.attempt_count == 1
        assert task.output_asset_id is not None
    await engine.dispose()


@pytest.mark.anyio
async def test_export_handler_releases_storage_failure_for_broker_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    requester_id, itinerary_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session:
        session.add_all((
            User(id=requester_id, phone=f"1{uuid.uuid4().int % 10**10:010d}"),
            Itinerary(id=itinerary_id, owner_id=requester_id, title="Trip", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7)),
        ))
        version = ItineraryVersion(itinerary_id=itinerary_id, version=1, created_by=requester_id, snapshot={"title": "Trip", "days": []})
        session.add(version)
        await session.flush()
        task = ExportTask(requester_id=requester_id, itinerary_id=itinerary_id, itinerary_version_id=version.id, version_no=1, idempotency_key="retry-key", snapshot_json={"title": "Trip", "days": []})
        session.add(task)
        await session.commit()
        monkeypatch.setattr(domain_handlers, "S3ObjectStorage", UnavailableStorage)
        with pytest.raises(StorageUnavailable):
            await domain_handlers._run_export(session, {"trace_id": str(uuid.uuid4()), "payload": {"export_task_id": task.id}})
        await session.refresh(task)
        assert task.status == "queued"
        assert task.progress == 0
        assert task.attempt_count == 1
        assert task.last_error_code == "EXPORT_STORAGE_UNAVAILABLE"
    await engine.dispose()
