import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.modules.auth.dependencies import get_auth_service
from app.modules.chat.models import Conversation, ConversationMember
from app.modules.media.models import MediaAsset
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.media.router import get_object_storage


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[int, str, str, str | None]] = {}
        self.put_requests: list[tuple[str, str, str, int]] = []
        self.get_requests: list[tuple[str, int]] = []

    async def presign_put(self, *, key: str, mime_type: str, sha256: str, expires_in: int) -> str:
        self.put_requests.append((key, mime_type, sha256, expires_in))
        return f"https://storage.test/{key}?put"

    async def head_object(self, *, key: str) -> tuple[int, str, str, str | None]:
        try:
            return self.objects[key]
        except KeyError as error:
            from app.integrations.object_storage import StorageUnavailable

            raise StorageUnavailable("missing") from error

    async def presign_get(self, *, key: str, expires_in: int) -> str:
        self.get_requests.append((key, expires_in))
        return f"https://storage.test/{key}?get"

    async def delete_object(self, *, key: str) -> None:
        self.objects.pop(key, None)


def test_private_media_upload_control_plane() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        from app.models.base import Base
        import app.modules.media.models  # noqa: F401

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth_service = AuthService(InMemoryTTLStore(), secret="media-router-test-secret")
        storage = FakeObjectStorage()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth_service
        app.dependency_overrides[get_object_storage] = lambda: storage
        try:
            with TestClient(app) as client:
                owner_headers = _headers(auth_service, "f15ae2ae-1a49-4531-9668-2db8c01772cb")
                other_headers = _headers(auth_service, "fef2c6b7-8cff-4527-a2b5-a1fcd62a4bd5")
                payload = {
                    "purpose": "avatar",
                    "mime_type": "image/png",
                    "size_bytes": 42,
                    "sha256": "a" * 64,
                }
                requested = client.post("/api/v1/media/upload-requests", headers=owner_headers, json=payload)
                assert requested.status_code == 201
                body = requested.json()
                assert body["headers"] == {"Content-Type": "image/png", "x-amz-meta-sha256": "a" * 64}
                assert body["upload_url"].endswith("?put")
                assert "/media/f15ae2ae-1a49-4531-9668-2db8c01772cb/" in body["upload_url"]

                asset_key = storage.put_requests[0][0]
                storage.objects[asset_key] = (42, "image/png", "etag-123", "a" * 64)
                completed = client.post(
                    f"/api/v1/media/{body['asset_id']}:complete",
                    headers=owner_headers,
                    json={"etag": "\"etag-123\"", "size_bytes": 42},
                )
                assert completed.status_code == 200
                assert completed.json() == {"id": body["asset_id"], "status": "completed", "mime_type": "image/png", "size_bytes": 42}

                download = client.get(f"/api/v1/media/{body['asset_id']}/download-url", headers=owner_headers)
                assert download.status_code == 200
                assert download.json()["url"].endswith("?get")
                assert storage.get_requests == [(asset_key, 300)]

                denied = client.get(f"/api/v1/media/{body['asset_id']}/download-url", headers=other_headers)
                assert denied.status_code == 404
                assert denied.json()["code"] == "MEDIA_ASSET_NOT_FOUND"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_upload_validation_and_head_object_mismatch_are_rejected() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        from app.models.base import Base
        import app.modules.media.models  # noqa: F401

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth_service = AuthService(InMemoryTTLStore(), secret="media-validation-test-secret")
        storage = FakeObjectStorage()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth_service
        app.dependency_overrides[get_object_storage] = lambda: storage
        try:
            with TestClient(app) as client:
                headers = _headers(auth_service, "6f4c8721-bd67-4861-9baf-330e1ed93104")
                invalid = client.post("/api/v1/media/upload-requests", headers=headers, json={
                    "purpose": "avatar", "mime_type": "image/gif", "size_bytes": 1, "sha256": "a" * 64,
                })
                assert invalid.status_code == 422

                requested = client.post("/api/v1/media/upload-requests", headers=headers, json={
                    "purpose": "avatar", "mime_type": "image/webp", "size_bytes": 42, "sha256": "b" * 64,
                })
                asset_id = requested.json()["asset_id"]
                storage.objects[storage.put_requests[0][0]] = (41, "image/webp", "etag-123", "b" * 64)
                mismatch = client.post(
                    f"/api/v1/media/{asset_id}:complete",
                    headers=headers,
                    json={"etag": "etag-123", "size_bytes": 42},
                )
                assert mismatch.status_code == 422
                assert mismatch.json()["code"] == "MEDIA_UPLOAD_INVALID"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_generic_media_download_hides_itinerary_exports() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        from app.models.base import Base
        import app.modules.media.models  # noqa: F401

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth_service = AuthService(InMemoryTTLStore(), secret="media-export-download-test-secret")
        storage = FakeObjectStorage()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth_service
        app.dependency_overrides[get_object_storage] = lambda: storage
        owner_id = "908c9d44-6133-43ac-b2b6-7b7d8a29f9a3"
        try:
            async with session_factory() as session:
                asset = MediaAsset(
                    owner_id=owner_id,
                    purpose="itinerary_export",
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    size_bytes=1,
                    sha256="a" * 64,
                    object_key="exports/private.docx",
                    status="completed",
                )
                session.add(asset)
                await session.commit()
            with TestClient(app) as client:
                response = client.get(f"/api/v1/media/{asset.id}/download-url", headers=_headers(auth_service, owner_id))
                assert response.status_code == 404
                assert response.json()["code"] == "MEDIA_ASSET_NOT_FOUND"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_group_avatar_download_is_limited_to_active_conversation_members() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        from app.models.base import Base, utc_now
        import app.modules.chat.models  # noqa: F401
        import app.modules.media.models  # noqa: F401

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        auth_service = AuthService(InMemoryTTLStore(), secret="group-avatar-download-test-secret")
        storage = FakeObjectStorage()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth_service
        app.dependency_overrides[get_object_storage] = lambda: storage
        owner_id = "908c9d44-6133-43ac-b2b6-7b7d8a29f9a3"
        member_id = "aa2e6c45-4a5d-4c52-a5f9-4b41cc47acc1"
        former_member_id = "ba2e6c45-4a5d-4c52-a5f9-4b41cc47acc2"
        outsider_id = "ca2e6c45-4a5d-4c52-a5f9-4b41cc47acc3"
        try:
            async with session_factory() as session:
                asset = MediaAsset(
                    owner_id=owner_id,
                    purpose="avatar",
                    mime_type="image/png",
                    size_bytes=1,
                    sha256="b" * 64,
                    object_key="media/private-group-avatar.png",
                    status="completed",
                )
                session.add(asset)
                await session.flush()
                conversation = Conversation(
                    conversation_type="companion_group",
                    title="Weekend walkers",
                    avatar_asset_id=asset.id,
                )
                session.add(conversation)
                await session.flush()
                session.add_all([
                    ConversationMember(conversation_id=conversation.id, user_id=owner_id, joined_at=utc_now()),
                    ConversationMember(conversation_id=conversation.id, user_id=member_id, joined_at=utc_now()),
                    ConversationMember(
                        conversation_id=conversation.id,
                        user_id=former_member_id,
                        joined_at=utc_now(),
                        left_at=utc_now(),
                    ),
                ])
                await session.commit()

            with TestClient(app) as client:
                member = client.get(
                    f"/api/v1/media/{asset.id}/download-url",
                    headers=_headers(auth_service, member_id),
                )
                former_member = client.get(
                    f"/api/v1/media/{asset.id}/download-url",
                    headers=_headers(auth_service, former_member_id),
                )
                outsider = client.get(
                    f"/api/v1/media/{asset.id}/download-url",
                    headers=_headers(auth_service, outsider_id),
                )

                assert member.status_code == 200
                assert member.json()["url"].endswith("?get")
                assert former_member.status_code == 404
                assert former_member.json()["code"] == "MEDIA_ASSET_NOT_FOUND"
                assert outsider.status_code == 404
                assert outsider.json()["code"] == "MEDIA_ASSET_NOT_FOUND"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _headers(auth_service: AuthService, user_id: str) -> dict[str, str]:
    token = auth_service.create_access_token(user_id=user_id, audience="consumer", roles=["user"])
    return {"Authorization": f"Bearer {token}"}
