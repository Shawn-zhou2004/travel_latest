import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.object_storage import StorageUnavailable
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.modules.media.models import MediaAsset
from app.modules.media.service import (
    MEDIA_UPLOAD_CLEANUP_EVENT,
    MediaError,
    MediaService,
    enqueue_expired_upload_cleanup,
    expire_pending_uploads,
)
from app.workers import domain_handlers
from app.events.consumer import registered_routes


class FakeCleanupStorage:
    def __init__(self, *, fail_deletes: bool = False) -> None:
        self.deleted_keys: list[str] = []
        self.fail_deletes = fail_deletes

    async def delete_object(self, *, key: str) -> None:
        self.deleted_keys.append(key)
        if self.fail_deletes:
            raise StorageUnavailable("unavailable")


def test_expiration_sweep_is_idempotent_and_preserves_completed_assets() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)
        storage = FakeCleanupStorage()
        try:
            async with factory() as session:
                expired_pending = MediaAsset(
                    owner_id="ce75578d-20fc-4d8e-b4d3-49ae6f9c84bc", purpose="avatar", mime_type="image/png",
                    size_bytes=1, sha256="a" * 64, object_key="media/expired", upload_expires_at=now - timedelta(seconds=1),
                )
                completed = MediaAsset(
                    owner_id="ce75578d-20fc-4d8e-b4d3-49ae6f9c84bc", purpose="avatar", mime_type="image/png",
                    size_bytes=1, sha256="b" * 64, object_key="media/completed", status="completed", upload_expires_at=now - timedelta(days=1),
                )
                session.add_all([expired_pending, completed])
                await session.commit()

                assert await expire_pending_uploads(session, storage, now=now) == 1
                await session.commit()
                assert expired_pending.status == "expired"
                assert completed.status == "completed"
                assert storage.deleted_keys == ["media/expired"]

                assert await expire_pending_uploads(session, storage, now=now) == 0
                await session.commit()
                assert storage.deleted_keys == ["media/expired"]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_expiration_remains_durable_when_object_delete_fails() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)
        try:
            async with factory() as session:
                asset = MediaAsset(
                    owner_id="c6a2de80-5acd-4789-8f39-10642140e0cb", purpose="avatar", mime_type="image/png",
                    size_bytes=1, sha256="a" * 64, object_key="media/orphan", upload_expires_at=now - timedelta(seconds=1),
                )
                session.add(asset)
                await session.commit()
                assert await expire_pending_uploads(session, FakeCleanupStorage(fail_deletes=True), now=now) == 1
                await session.commit()
                assert asset.status == "expired"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_expired_upload_cannot_complete_and_cleanup_event_is_durable() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                asset = MediaAsset(
                    owner_id="6ac341c4-2e6c-4d44-8c5d-b4fbc17608c2", purpose="avatar", mime_type="image/png",
                    size_bytes=1, sha256="a" * 64, object_key="media/late", upload_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
                session.add(asset)
                event = enqueue_expired_upload_cleanup(session)
                await session.commit()

                with pytest.raises(MediaError, match="expired") as error:
                    await MediaService(session, FakeCleanupStorage()).complete_upload(
                        asset.id, asset.owner_id, etag="etag", size_bytes=1
                    )
                assert error.value.code == "MEDIA_ASSET_EXPIRED"
                assert asset.status == "expired"
                with pytest.raises(MediaError, match="expired") as error:
                    await MediaService(session, FakeCleanupStorage()).download_url(asset.id, asset.owner_id)
                assert error.value.code == "MEDIA_ASSET_EXPIRED"
                assert event.event_type == MEDIA_UPLOAD_CLEANUP_EVENT
                assert await session.get(OutboxEvent, event.event_id) is not None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_cleanup_handler_is_registered_and_expires_records(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        storage = FakeCleanupStorage()
        monkeypatch.setattr(domain_handlers, "S3ObjectStorage", lambda *_args, **_kwargs: storage)
        try:
            async with factory() as session:
                asset = MediaAsset(
                    owner_id="4d4bf3e3-766c-4bd5-8d98-36a9cb564ffc", purpose="avatar", mime_type="image/png",
                    size_bytes=1, sha256="a" * 64, object_key="media/handler", upload_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
                session.add(asset)
                await session.commit()
                await domain_handlers._cleanup_expired_media_uploads(session, {"payload": {}})
                await session.commit()
                assert asset.status == "expired"
                assert storage.deleted_keys == ["media/handler"]
        finally:
            await engine.dispose()

    domain_handlers.register_domain_handlers()
    routes = registered_routes.snapshot()[MEDIA_UPLOAD_CLEANUP_EVENT]
    assert any(route.consumer_name == "media.expired_upload_cleanup" for route in routes)
    asyncio.run(scenario())
