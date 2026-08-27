import asyncio
from collections.abc import AsyncIterator
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.itineraries.models import Itinerary, ItineraryVersion, TripCollaborator
from app.modules.community.models import Post
from app.modules.media.models import MediaAsset


def test_field_note_publish_route_authorizes_and_projects_snapshot() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="field-note-router-test")
        async with sessions() as session:
            owner, editor, viewer, outsider = (User(phone="13600000003"), User(phone="13600000004"), User(phone="13600000005"), User(phone="13600000006"))
            session.add_all([owner, editor, viewer, outsider])
            await session.flush()
            itinerary = Itinerary(owner_id=owner.id, title="Trip", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
            session.add(itinerary)
            await session.flush()
            version = ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={"title": "Frozen trip", "start_date": "2026-10-01", "end_date": "2026-10-01", "destination": {"name": "Hangzhou", "city_code": "330100"}, "days": [{"id": "day-id", "day_date": "2026-10-01", "display_order": 0, "events": [{"id": "event-id", "poi_id": "poi-1", "poi_snapshot": {"name": "Stop"}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": "Note"}], "route_segments": [], "route_calculation": {"id": "job-id"}}]})
            empty_version = ItineraryVersion(itinerary_id=itinerary.id, version=2, created_by=owner.id, snapshot={"title": "Empty trip", "start_date": "2026-10-01", "end_date": "2026-10-01", "days": [{"day_date": "2026-10-01", "display_order": 0, "events": []}]})
            image = MediaAsset(owner_id=editor.id, purpose="field_note", mime_type="image/webp", size_bytes=1, sha256="d" * 64, object_key="router-image", status="completed")
            owner_image = MediaAsset(owner_id=owner.id, purpose="field_note", mime_type="image/png", size_bytes=1, sha256="e" * 64, object_key="owner-router-image", status="completed")
            session.add_all([version, empty_version, image, owner_image, TripCollaborator(itinerary_id=itinerary.id, user_id=editor.id, role="editor", status="accepted"), TripCollaborator(itinerary_id=itinerary.id, user_id=viewer.id, role="viewer", status="accepted")])
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = lambda user: {"Authorization": f"Bearer {auth.create_access_token(user_id=user.id, audience='consumer', roles=['user'])}"}
        payload = {"version_no": 1, "title": "Field note", "recap_text": "A good stop.", "cover_media_id": image.id, "media_ids": [image.id]}
        try:
            with TestClient(app) as client:
                response = client.post(f"/api/v1/itineraries/{itinerary.id}/field-notes", headers=headers(editor), json=payload)
                assert response.status_code == 201
                body = response.json()
                assert body["status"] == "pending_review"
                assert body["day_count"] == 1 and body["stop_count"] == 1
                assert body["media_ids"] == [image.id]
                assert body["city_code"] == "330100"
                assert body["itinerary_snapshot"]["days"] == [{"day_date": "2026-10-01", "display_order": 0, "events": [{"poi_id": "poi-1", "poi_snapshot": {"name": "Stop"}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": "Note"}]}]
                owner_payload = {**payload, "title": "Owner field note", "cover_media_id": owner_image.id, "media_ids": [owner_image.id]}
                assert client.post(f"/api/v1/itineraries/{itinerary.id}/field-notes", headers=headers(owner), json=owner_payload).status_code == 201
                assert client.post(f"/api/v1/itineraries/{itinerary.id}/field-notes", headers=headers(viewer), json=payload).status_code == 403
                assert client.post(f"/api/v1/itineraries/{itinerary.id}/field-notes", headers=headers(outsider), json=payload).status_code == 403
                assert client.post("/api/v1/posts", headers=headers(owner), json={"content_type": "itinerary", "title": "Unfrozen", "body_text": ""}).status_code == 422
                invalid_cover = client.post(f"/api/v1/itineraries/{itinerary.id}/field-notes", headers=headers(owner), json={**owner_payload, "cover_media_id": "not-in-media"})
                assert invalid_cover.status_code == 422
                no_events = client.post(f"/api/v1/itineraries/{itinerary.id}/field-notes", headers=headers(owner), json={**owner_payload, "version_no": 2})
                assert no_events.status_code == 422
                invalid_version = client.post(f"/api/v1/itineraries/{itinerary.id}/field-notes", headers=headers(owner), json={**owner_payload, "version_no": 9})
                assert invalid_version.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_field_note_read_and_copy_routes_are_public_read_and_idempotent() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="field-note-copy-router-test")
        async with sessions() as session:
            author, reader = User(phone="13600000007"), User(phone="13600000008")
            session.add_all([author, reader])
            await session.flush()
            snapshot = {
                "title": "Frozen route", "start_date": "2026-10-01", "end_date": "2026-10-01",
                "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [{"poi_id": "poi-1", "poi_snapshot": {"name": "Lake"}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": None}]}],
            }
            published = Post(author_id=author.id, content_type="itinerary", title="Frozen route", recap_text="Go early", city_code="330100", status="published", itinerary_snapshot_json=snapshot)
            pending = Post(author_id=author.id, content_type="itinerary", title="Pending", recap_text="Later", status="pending_review", itinerary_snapshot_json=snapshot)
            session.add_all([published, pending])
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=reader.id, audience='consumer', roles=['user'])}"}
        try:
            with TestClient(app) as client:
                feed = client.get("/api/v1/posts", params={"content_type": "itinerary", "city_code": "330100", "q": "early"})
                assert feed.status_code == 200
                assert [item["id"] for item in feed.json()["items"]] == [published.id]
                detail = client.get(f"/api/v1/posts/{published.id}")
                assert detail.status_code == 200 and detail.json()["stop_count"] == 1
                assert client.get(f"/api/v1/posts/{pending.id}").status_code == 404
                missing_key = client.post(f"/api/v1/posts/{published.id}:copy-itinerary", headers=headers)
                assert missing_key.status_code == 422
                first = client.post(f"/api/v1/posts/{published.id}:copy-itinerary", headers={**headers, "Idempotency-Key": "router-key"})
                retry = client.post(f"/api/v1/posts/{published.id}:copy-itinerary", headers={**headers, "Idempotency-Key": "router-key"})
                assert first.status_code == 201 and retry.status_code == 201
                assert first.json()["idempotent"] is False and retry.json()["idempotent"] is True
                assert first.json()["itinerary"]["id"] == retry.json()["itinerary"]["id"]
                assert first.json()["source_post_id"] == published.id
        finally:
            await engine.dispose()

    asyncio.run(scenario())
