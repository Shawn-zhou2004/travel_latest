import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import AdminAction, CommunityKnowledgeReview
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.community.models import Post


def test_platform_admin_can_identify_field_note_without_snapshot_disclosure() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="field-note-admin-list-test-secret")
        async with factory() as session:
            admin = User(phone="13600000104")
            author = User(phone="13600000105")
            session.add_all([admin, author])
            await session.flush()
            post = Post(
                author_id=author.id,
                content_type="itinerary",
                title="West Lake field note",
                body_text="",
                status="pending_review",
                moderation_reason=None,
                itinerary_snapshot_json={"title": "Private source data must not appear", "days": []},
            )
            session.add(post)
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['platform_admin'])}"}
        try:
            with TestClient(app) as client:
                response = client.get("/api/v1/admin/posts", headers=headers, params={"status": "pending_review"})
                assert response.status_code == 200
                item = response.json()["items"][0]
                assert item == {
                    "id": post.id,
                    "author_id": author.id,
                    "content_type": "itinerary",
                    "title": "West Lake field note",
                    "body": "",
                    "status": "pending_review",
                    "moderation_reason": None,
                    "has_route_snapshot": True,
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                }
                assert "itinerary_snapshot_json" not in item
                assert "Private source data must not appear" not in str(item)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_platform_admin_reviews_community_knowledge_once_with_safe_index_event_and_audit() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="community-knowledge-review-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000106")
            author = User(phone="13600000107")
            session.add_all([admin, author])
            await session.flush()
            post = Post(author_id=author.id, content_type="note", title="Useful route", body_text="Take the early bus to avoid the queue.", city_code="330100", status="published")
            session.add(post)
            await session.flush()
            review = CommunityKnowledgeReview(post_id=post.id)
            session.add(review)
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['platform_admin'])}"}
        non_admin_headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['provider_admin'])}"}
        try:
            with TestClient(app) as client:
                assert client.get("/api/v1/admin/ai/community-knowledge-reviews", headers=non_admin_headers).status_code == 403
                assert client.patch(f"/api/v1/admin/ai/community-knowledge-reviews/{post.id}", headers=non_admin_headers, json={"status": "approved"}).status_code == 403
                queued = client.get("/api/v1/admin/ai/community-knowledge-reviews", headers=admin_headers)
                assert queued.status_code == 200
                assert queued.json()["items"][0]["id"] == review.id
                approved = client.patch(f"/api/v1/admin/ai/community-knowledge-reviews/{post.id}", headers=admin_headers, json={"status": "approved"})
                assert approved.status_code == 200
                assert approved.json()["status"] == "approved"
                assert client.patch(f"/api/v1/admin/ai/community-knowledge-reviews/{post.id}", headers=admin_headers, json={"status": "approved"}).status_code == 409
            async with factory() as session:
                stored = await session.get(CommunityKnowledgeReview, review.id)
                stored_post = await session.get(Post, post.id)
                event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == review.id))
                audit = await session.scalar(select(AdminAction).where(AdminAction.target_id == review.id))
                assert stored is not None and stored.status == "approved" and stored.reviewed_by == admin.id
                assert stored_post is not None and stored_post.status == "published"
                assert event is not None and event.event_type == "ai.community_knowledge_index_requested"
                assert dict(event.payload_json) == {"post_id": post.id, "review_id": review.id}
                assert post.body_text not in str(event.payload_json)
                assert audit is not None and audit.action == "ai_community_knowledge_review.approved"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_community_knowledge_rejection_requires_reason_and_emits_no_event() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="community-knowledge-rejection-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000108")
            author = User(phone="13600000109")
            session.add_all([admin, author])
            await session.flush()
            post = Post(author_id=author.id, content_type="note", title="Unverified route", body_text="Maybe take this route.", status="published")
            session.add(post)
            await session.flush()
            review = CommunityKnowledgeReview(post_id=post.id)
            session.add(review)
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=admin.id, audience='admin', roles=['platform_admin'])}"}
        try:
            with TestClient(app) as client:
                assert client.patch(f"/api/v1/admin/ai/community-knowledge-reviews/{post.id}", headers=headers, json={"status": "rejected", "reason": "   "}).status_code == 422
                rejected = client.patch(f"/api/v1/admin/ai/community-knowledge-reviews/{post.id}", headers=headers, json={"status": "rejected", "reason": "The advice cannot be verified."})
                assert rejected.status_code == 200
                assert rejected.json()["reason"] == "The advice cannot be verified."
            async with factory() as session:
                stored = await session.get(CommunityKnowledgeReview, review.id)
                events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == review.id))).all()
                audit = await session.scalar(select(AdminAction).where(AdminAction.target_id == review.id))
                assert stored is not None and stored.status == "rejected" and stored.reason == "The advice cannot be verified."
                assert not events
                assert audit is not None and audit.reason == "The advice cannot be verified."
        finally:
            await engine.dispose()

    asyncio.run(scenario())
