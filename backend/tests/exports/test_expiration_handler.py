from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.events.consumer import registered_routes
from app.models.base import Base
from app.modules.exports.service import EXPORT_EXPIRATION_CLEANUP_EVENT
from app.workers import domain_handlers


class FakeStorage:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    async def delete_object(self, *, key: str) -> None:
        self.deleted_keys.append(key)


def test_export_expiration_handler_uses_export_bucket_and_is_registered(monkeypatch) -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        storage = FakeStorage()
        received: list[object] = []

        def create_storage(settings, *, bucket):
            received.extend((settings, bucket))
            return storage

        monkeypatch.setattr(domain_handlers, "Settings", lambda: SimpleNamespace(s3_bucket_exports="exports"))
        monkeypatch.setattr(domain_handlers, "S3ObjectStorage", create_storage)
        try:
            async with factory() as session:
                monkeypatch.setattr(domain_handlers, "expire_succeeded_exports", lambda *_args: asyncio.sleep(0, result=0))
                await domain_handlers._cleanup_expired_exports(session, {"payload": {}})
                assert received[1] == "exports"
        finally:
            await engine.dispose()

    domain_handlers.register_domain_handlers()
    routes = registered_routes.snapshot()[EXPORT_EXPIRATION_CLEANUP_EVENT]
    assert any(route.consumer_name == "exports.expiration_cleanup" for route in routes)
    asyncio.run(scenario())
