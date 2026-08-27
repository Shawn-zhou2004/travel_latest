import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base, new_uuid
from app.models.user import User, UserRole, UserStatus
from app.modules.admin.models import AdminAction
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def test_admin_user_directory_is_authorized_masked_and_deterministic() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-users-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000061", created_at=datetime(2026, 1, 1, tzinfo=UTC), updated_at=datetime(2026, 1, 1, tzinfo=UTC))
            first_id, second_id = sorted((new_uuid(), new_uuid()))
            first = User(id=first_id, phone="13812345678", nickname="Alice", created_at=datetime(2026, 1, 2, tzinfo=UTC), updated_at=datetime(2026, 1, 2, tzinfo=UTC))
            second = User(id=second_id, phone="13987654321", nickname="Bob", created_at=datetime(2026, 1, 2, tzinfo=UTC), updated_at=datetime(2026, 1, 2, tzinfo=UTC))
            session.add_all([admin, first, second])
            await session.flush()
            provider_id = new_uuid()
            session.add_all([UserRole(user_id=first.id, role="user"), UserRole(user_id=first.id, role="provider_staff", scope_key=provider_id)])
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        consumer_token = auth.create_access_token(user_id=first.id, audience="consumer", roles=["user"])
        try:
            with TestClient(app) as client:
                denied = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {consumer_token}"})
                assert denied.status_code == 403
                response = client.get("/api/v1/admin/users", params={"limit": 2}, headers={"Authorization": f"Bearer {admin_token}"})
                assert response.status_code == 200
                body = response.json()
                assert [item["nickname"] for item in body["items"]] == [None, "Alice"]
                assert body["items"][1]["phone_masked"] == "138****5678"
                assert "13812345678" not in response.text
                assert all(item["status"] == "active" for item in body["items"])
                assert body["items"][1]["provider_memberships"] == [provider_id]
                assert body["next_cursor"]
                next_page = client.get("/api/v1/admin/users", params={"limit": 2, "cursor": body["next_cursor"]}, headers={"Authorization": f"Bearer {admin_token}"})
                assert [item["nickname"] for item in next_page.json()["items"]] == ["Bob"]
                filtered = client.get("/api/v1/admin/users", params={"query": "Alice"}, headers={"Authorization": f"Bearer {admin_token}"})
                assert [item["id"] for item in filtered.json()["items"]] == [first.id]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admin_can_update_status_and_unscoped_roles_with_audit_record() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-users-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000061")
            second_admin = User(phone="13600000062")
            target = User(phone="13600000063")
            session.add_all([admin, second_admin, target])
            await session.flush()
            session.add_all([
                UserRole(user_id=admin.id, role="platform_admin"),
                UserRole(user_id=second_admin.id, role="platform_admin"),
                UserRole(user_id=target.id, role="user"),
            ])
            await session.commit()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        try:
            with TestClient(app) as client:
                response = client.patch(
                    f"/api/v1/admin/users/{target.id}",
                    json={"status": "suspended", "roles": ["user", "platform_admin"]},
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert response.status_code == 200
                assert response.json()["status"] == "suspended"
                assert response.json()["roles"] == ["platform_admin", "user"]
            async with factory() as session:
                saved = await session.get(User, target.id)
                audit = await session.scalar(select(AdminAction).where(AdminAction.target_id == target.id))
                assert saved is not None and saved.status == UserStatus.SUSPENDED
                assert audit is not None
                assert audit.actor_id == admin.id
                assert audit.action == "user.updated"
                assert audit.result_json == {"status": "suspended", "roles": ["platform_admin", "user"]}
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admin_user_updates_validate_authorization_scopes_and_last_admin() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-users-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000061")
            target = User(phone="13600000062")
            scoped = User(phone="13600000063")
            session.add_all([admin, target, scoped])
            await session.flush()
            session.add_all([
                UserRole(user_id=admin.id, role="platform_admin"),
                UserRole(user_id=target.id, role="user"),
                UserRole(user_id=scoped.id, role="provider_staff", scope_key=new_uuid()),
            ])
            await session.commit()
        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        user_token = auth.create_access_token(user_id=target.id, audience="consumer", roles=["user"])
        try:
            with TestClient(app) as client:
                assert client.patch(f"/api/v1/admin/users/{target.id}", json={"status": "suspended"}, headers={"Authorization": f"Bearer {user_token}"}).status_code == 403
                invalid = client.patch(f"/api/v1/admin/users/{target.id}", json={"roles": ["unknown"]}, headers={"Authorization": f"Bearer {admin_token}"})
                assert invalid.status_code == 422
                scoped_role = client.patch(f"/api/v1/admin/users/{scoped.id}", json={"roles": ["provider_staff"]}, headers={"Authorization": f"Bearer {admin_token}"})
                assert scoped_role.status_code == 422
                assert scoped_role.json()["code"] == "PROVIDER_ROLE_SCOPE_REQUIRED"
                last_admin = client.patch(f"/api/v1/admin/users/{admin.id}", json={"status": "suspended"}, headers={"Authorization": f"Bearer {admin_token}"})
                assert last_admin.status_code == 409
                assert last_admin.json()["code"] == "LAST_ACTIVE_PLATFORM_ADMIN"
                removal = client.patch(f"/api/v1/admin/users/{admin.id}", json={"roles": []}, headers={"Authorization": f"Bearer {admin_token}"})
                assert removal.status_code == 409
        finally:
            await engine.dispose()

    asyncio.run(scenario())
