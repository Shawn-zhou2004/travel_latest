import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.admin.models import AdminAction
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.community.models import Post


def test_admin_can_publish_a_pending_post_and_audit_the_decision() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-router-test-secret")
        async with factory() as setup_session:
            admin = User(phone="13600000011")
            author = User(phone="13600000012")
            setup_session.add_all([admin, author])
            await setup_session.flush()
            post = Post(author_id=author.id, title="Review me", body_text="Pending", status="pending_review")
            setup_session.add(post)
            await setup_session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        consumer_token = auth.create_access_token(user_id=author.id, audience="consumer", roles=["user"])

        try:
            with TestClient(app) as client:
                denied = client.get("/api/v1/admin/posts", headers={"Authorization": f"Bearer {consumer_token}"})
                assert denied.status_code == 403
                response = client.patch(
                    f"/api/v1/admin/posts/{post.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"status": "published", "moderation_reason": "Policy review complete."},
                )
                assert response.status_code == 200
                assert response.json()["status"] == "published"
            async with factory() as verify_session:
                stored_post = await verify_session.get(Post, post.id)
                audit = await verify_session.scalar(select(AdminAction).where(AdminAction.target_id == post.id))
                assert stored_post is not None and stored_post.status == "published"
                assert audit is not None
                assert audit.actor_id == admin.id
                assert audit.reason == "Policy review complete."
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admin_decision_requires_a_reason() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="admin-router-test-secret")
        async with factory() as setup_session:
            admin = User(phone="13600000013")
            author = User(phone="13600000014")
            setup_session.add_all([admin, author])
            await setup_session.flush()
            post = Post(author_id=author.id, title="Review me", body_text="Pending", status="pending_review")
            setup_session.add(post)
            await setup_session.commit()

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
                    f"/api/v1/admin/posts/{post.id}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"status": "published", "moderation_reason": ""},
                )
                assert response.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(scenario())
