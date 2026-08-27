from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.exports.models import ExportTask
from app.modules.exports.schemas import ExportTaskCreate
from app.modules.exports.service import (
    DOCX_MIME_TYPE,
    EXPORT_EXPIRATION_CLEANUP_EVENT,
    ExportTaskError,
    ExportTaskService,
    enqueue_expired_export_cleanup,
    expire_succeeded_exports,
)
from app.modules.itineraries.models import Itinerary, ItineraryVersion
from app.modules.media.models import MediaAsset


class FakeStorage:
    def __init__(self) -> None:
        self.uploads: dict[str, bytes] = {}

    async def upload_bytes(self, *, key: str, data: bytes, mime_type: str, sha256: str) -> str:
        assert mime_type == DOCX_MIME_TYPE
        self.uploads[key] = data
        return "fake-etag"

    async def presign_attachment_get(self, *, key: str, filename: str, expires_in: int) -> str:
        assert key in self.uploads
        assert filename.endswith(".docx")
        assert expires_in == 300
        return "https://storage.example/private-download"

    async def delete_object(self, *, key: str) -> None:
        self.uploads.pop(key, None)


class FailingDeleteStorage(FakeStorage):
    async def delete_object(self, *, key: str) -> None:
        raise RuntimeError("storage unavailable")


@pytest.mark.anyio
async def test_export_creation_uses_immutable_version_snapshot_and_idempotency() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    requester_id, itinerary_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session:
        session.add(User(id=requester_id, phone=f"1{uuid.uuid4().int % 10**10:010d}"))
        itinerary = Itinerary(id=itinerary_id, owner_id=requester_id, title="Live title", start_date=date(2026, 8, 7), end_date=date(2026, 8, 8))
        version = ItineraryVersion(itinerary_id=itinerary_id, version=1, created_by=requester_id, snapshot={"title": "Frozen title", "days": []})
        session.add_all((itinerary, version))
        await session.commit()
        service = ExportTaskService(session)
        request = ExportTaskCreate(itinerary_id=itinerary_id, version_no=1)
        task = await service.create(requester_id, "same-key", request)
        duplicate = await service.create(requester_id, "same-key", request)
        assert duplicate.id == task.id
        assert task.snapshot_json["title"] == "Frozen title"
        assert task.itinerary_version_id == version.id
        with pytest.raises(ExportTaskError, match="Idempotency"):
            await service.create(requester_id, "same-key", ExportTaskCreate(itinerary_id=itinerary_id, version_no=2))
    await engine.dispose()


@pytest.mark.anyio
async def test_expiration_remains_durable_when_export_object_delete_fails() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    requester_id, itinerary_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    async with factory() as session:
        session.add_all((
            User(id=requester_id, phone=f"1{uuid.uuid4().int % 10**10:010d}"),
            Itinerary(id=itinerary_id, owner_id=requester_id, title="Trip", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7)),
        ))
        version = ItineraryVersion(itinerary_id=itinerary_id, version=1, created_by=requester_id, snapshot={})
        session.add(version)
        await session.flush()
        asset = MediaAsset(
            owner_id=requester_id, purpose="itinerary_export", mime_type=DOCX_MIME_TYPE,
            size_bytes=1, sha256="b" * 64, object_key="exports/delete-failure.docx", status="completed",
            upload_expires_at=now - timedelta(seconds=1),
        )
        session.add(asset)
        await session.flush()
        task = ExportTask(
            requester_id=requester_id, itinerary_id=itinerary_id, itinerary_version_id=version.id,
            version_no=1, idempotency_key="delete-failure", snapshot_json={}, status="succeeded", progress=100,
            output_asset_id=asset.id, expires_at=now - timedelta(seconds=1),
        )
        session.add(task)
        await session.commit()
        assert await expire_succeeded_exports(session, FailingDeleteStorage(), now=now) == 1
        await session.commit()
        assert task.status == "expired"
        assert asset.status == "completed"
    await engine.dispose()


@pytest.mark.anyio
async def test_export_output_is_private_completed_and_download_is_requester_scoped() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    requester_id, itinerary_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session:
        session.add_all((
            User(id=requester_id, phone=f"1{uuid.uuid4().int % 10**10:010d}"),
            Itinerary(id=itinerary_id, owner_id=requester_id, title="Trip", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7)),
            ItineraryVersion(itinerary_id=itinerary_id, version=1, created_by=requester_id, snapshot={"title": "Trip", "days": []}),
        ))
        await session.commit()
        service = ExportTaskService(session)
        task = await service.create(requester_id, "output-key", ExportTaskCreate(itinerary_id=itinerary_id, version_no=1))
        assert await service.start_attempt(task.id) is not None
        storage = FakeStorage()
        await service.complete(task.id, b"docx bytes", storage)
        await session.commit()
        asset = await session.get(MediaAsset, task.output_asset_id)
        assert asset is not None
        assert asset.status == "completed"
        assert task.expires_at is not None
        assert asset.upload_expires_at is not None
        assert task.expires_at is not None
        assert asset.upload_expires_at.replace(tzinfo=UTC) == task.expires_at
        assert asset.mime_type == DOCX_MIME_TYPE
        assert asset.object_key == f"exports/{requester_id}/{task.id}.docx"
        completed_event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.event_type == "export_task.completed")
        )
        assert completed_event is not None
        assert completed_event.payload_json == {
            "export_task_id": task.id,
            "status": "succeeded",
            "asset_id": task.output_asset_id,
            "error_code": None,
            "user_id": requester_id,
        }
        url, _ = await service.download_url(task.id, requester_id, storage)
        assert url == "https://storage.example/private-download"
        with pytest.raises(ExportTaskError) as error:
            await service.download_url(task.id, str(uuid.uuid4()), storage)
        assert error.value.status_code == 404
    await engine.dispose()


@pytest.mark.anyio
async def test_expiration_is_idempotent_denies_download_and_preserves_non_succeeded_tasks() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    requester_id, itinerary_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    async with factory() as session:
        session.add_all((
            User(id=requester_id, phone=f"1{uuid.uuid4().int % 10**10:010d}"),
            Itinerary(id=itinerary_id, owner_id=requester_id, title="Trip", start_date=date(2026, 8, 7), end_date=date(2026, 8, 7)),
        ))
        version = ItineraryVersion(itinerary_id=itinerary_id, version=1, created_by=requester_id, snapshot={"title": "Trip", "days": []})
        session.add(version)
        await session.flush()
        asset = MediaAsset(
            owner_id=requester_id, purpose="itinerary_export", mime_type=DOCX_MIME_TYPE,
            size_bytes=1, sha256="a" * 64, object_key="exports/expired.docx", status="completed",
            upload_expires_at=now - timedelta(seconds=1),
        )
        session.add(asset)
        await session.flush()
        task = ExportTask(
            requester_id=requester_id, itinerary_id=itinerary_id, itinerary_version_id=version.id,
            version_no=1, idempotency_key="expired", snapshot_json={}, status="succeeded", progress=100,
            output_asset_id=asset.id, expires_at=now - timedelta(seconds=1),
        )
        queued = ExportTask(
            requester_id=requester_id, itinerary_id=itinerary_id, itinerary_version_id=version.id,
            version_no=1, idempotency_key="queued", snapshot_json={}, status="queued", progress=0,
            expires_at=now - timedelta(seconds=1),
        )
        session.add_all((task, queued))
        event = enqueue_expired_export_cleanup(session)
        await session.commit()
        assert event.event_type == EXPORT_EXPIRATION_CLEANUP_EVENT
        assert await session.get(OutboxEvent, event.event_id) is not None
        storage = FakeStorage()
        storage.uploads[asset.object_key] = b"docx bytes"
        assert await expire_succeeded_exports(session, storage, now=now) == 1
        await session.commit()
        assert task.status == "expired"
        assert asset.status == "completed"
        assert queued.status == "queued"
        assert asset.object_key not in storage.uploads
        assert await expire_succeeded_exports(session, storage, now=now) == 0
        with pytest.raises(ExportTaskError) as error:
            await ExportTaskService(session).download_url(task.id, requester_id, storage)
        assert error.value.code == "EXPORT_EXPIRED"
    await engine.dispose()
