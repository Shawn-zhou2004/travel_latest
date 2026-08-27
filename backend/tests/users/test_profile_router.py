import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.media.models import MediaAsset


def test_consumer_can_read_and_update_owned_profile() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="profile-test-secret")
        async with factory() as session:
            user = User(phone="13800000001")
            session.add(user)
            await session.flush()
            asset = MediaAsset(owner_id=user.id, purpose="avatar", mime_type="image/png", size_bytes=1, sha256="a" * 64, object_key="avatar-1", status="completed")
            session.add(asset)
            await session.commit()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=user.id, audience="consumer", roles=["user"])
        with TestClient(app) as client:
            assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["nickname"] is None
            response = client.patch("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}, json={"nickname": "Lin", "avatar_asset_id": asset.id})
            assert response.status_code == 200
            assert response.json()["nickname"] == "Lin"
            assert response.json()["avatar_asset_id"] == asset.id
            read = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert read.json()["nickname"] == "Lin"
            assert read.json()["avatar_asset_id"] == asset.id
        await engine.dispose()

    asyncio.run(scenario())


def test_profile_rejects_missing_or_foreign_avatar_asset() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="profile-ownership-test-secret")
        async with factory() as session:
            user = User(phone="13800000002")
            owner = User(phone="13800000003")
            session.add_all([user, owner])
            await session.flush()
            asset = MediaAsset(owner_id=owner.id, purpose="avatar", mime_type="image/png", size_bytes=1, sha256="b" * 64, object_key="avatar-2", status="completed")
            session.add(asset)
            await session.commit()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=user.id, audience="consumer", roles=["user"])
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app) as client:
            assert client.patch("/api/v1/users/me", headers=headers, json={"avatar_asset_id": "missing"}).status_code == 404
            assert client.patch("/api/v1/users/me", headers=headers, json={"avatar_asset_id": asset.id}).status_code == 404
        await engine.dispose()

    asyncio.run(scenario())
