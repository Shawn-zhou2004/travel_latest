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
from app.modules.community.models import CompanionApplication, CompanionRequest
from app.modules.itineraries.models import Itinerary, ItineraryVersion, TripCollaborator
from app.modules.media.models import MediaAsset


def test_itinerary_companion_plan_route_requires_editor_and_uses_current_snapshot() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="companion-plan-router-test")
        async with sessions() as session:
            owner, editor, viewer = User(phone="13700000005"), User(phone="13700000006"), User(phone="13700000007")
            session.add_all([owner, editor, viewer])
            await session.flush()
            itinerary = Itinerary(owner_id=owner.id, title="Live", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
            session.add(itinerary)
            await session.flush()
            session.add_all([
                TripCollaborator(itinerary_id=itinerary.id, user_id=editor.id, role="editor", status="accepted"),
                TripCollaborator(itinerary_id=itinerary.id, user_id=viewer.id, role="viewer", status="accepted"),
                ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={
                    "title": "Current route", "start_date": "2026-10-01", "end_date": "2026-10-01",
                    "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [
                        {"poi_id": "poi-1", "poi_snapshot": {"city": "330100"}, "display_order": 0},
                    ]}],
                }),
            ])
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = lambda user: {"Authorization": f"Bearer {auth.create_access_token(user_id=user.id, audience='consumer', roles=['user'])}"}
        payload = {"party_size": 3, "budget_min": 600, "budget_max": 900, "currency": "CNY", "travel_pace": "balanced", "interest_tags": ["citywalk"], "intro_text": "Walk together."}
        try:
            with TestClient(app) as client:
                created = client.post(f"/api/v1/itineraries/{itinerary.id}/companion-requests", headers=headers(editor), json=payload)
                assert created.status_code == 201
                assert created.json()["title"] == "Current route"
                assert created.json()["itinerary_id"] == itinerary.id
                assert client.post(f"/api/v1/itineraries/{itinerary.id}/companion-requests", headers=headers(viewer), json=payload).status_code == 403
                assert client.post("/api/v1/companion-requests", headers=headers(owner), json=payload).status_code == 405
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_itinerary_companion_plan_route_requires_or_accepts_fallback_city() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="companion-city-fallback-router-test")
        async with sessions() as session:
            owner = User(phone="13700000037")
            session.add(owner)
            await session.flush()
            itinerary = Itinerary(owner_id=owner.id, title="Legacy", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
            session.add(itinerary)
            await session.flush()
            session.add(ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={
                "title": "Legacy route", "start_date": "2026-10-01", "end_date": "2026-10-01",
                "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [
                    {"poi_id": "poi-1", "poi_snapshot": {"name": "Legacy stop"}, "display_order": 0},
                ]}],
            }))
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=owner.id, audience='consumer', roles=['user'])}"}
        payload = {"party_size": 3, "budget_min": 600, "budget_max": 900, "currency": "CNY", "travel_pace": "balanced", "interest_tags": ["citywalk"], "intro_text": "Walk together."}
        try:
            with TestClient(app) as client:
                missing = client.post(f"/api/v1/itineraries/{itinerary.id}/companion-requests", headers=headers, json=payload)
                created = client.post(
                    f"/api/v1/itineraries/{itinerary.id}/companion-requests",
                    headers=headers,
                    json={**payload, "city_code": "330100"},
                )
            assert missing.status_code == 422
            assert missing.json()["code"] == "COMPANION_DESTINATION_REQUIRED"
            assert missing.json()["message"] == "请选择目的地城市后再发布同行计划。"
            assert created.status_code == 201
            assert created.json()["city_code"] == "330100"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_discovery_detail_and_mine_use_safe_typed_projections() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="companion-discovery-router-test")
        async with sessions() as session:
            owner, applicant, member = User(phone="13700000017"), User(phone="13700000018"), User(phone="13700000019")
            session.add_all([owner, applicant, member])
            await session.flush()
            itinerary = Itinerary(owner_id=owner.id, title="Private route", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
            session.add(itinerary)
            await session.flush()
            session.add(ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={
                "title": "Private route", "start_date": "2026-10-01", "end_date": "2026-10-01", "days": [{
                    "day_date": "2026-10-01", "display_order": 0, "events": [{
                        "poi_id": "poi-1", "poi_snapshot": {"name": "West Lake", "city": "330100"},
                        "display_order": 0, "notes": "private note",
                    }],
                }],
            }))
            plan = CompanionRequest(owner_id=owner.id, itinerary_id=itinerary.id, title="Private route", city_code="330100", description="legacy", trip_kind="trip", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1), party_size=3, accepted_count=2, travel_pace="slow", interest_tags=["citywalk"], intro_text="Public intro", review_status="approved", status="open")
            session.add(plan)
            await session.flush()
            session.add_all([
                CompanionApplication(request_id=plan.id, applicant_id=applicant.id, message="contact me", status="pending"),
                CompanionApplication(request_id=plan.id, applicant_id=member.id, message="contact me", status="accepted"),
            ])
            await session.commit()
        app = create_app()
        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = lambda user: {"Authorization": f"Bearer {auth.create_access_token(user_id=user.id, audience='consumer', roles=['user'])}"}
        try:
            with TestClient(app) as client:
                listing = client.get("/api/v1/companion-requests?city_code=330100&tags=citywalk")
                public = client.get(f"/api/v1/companion-requests/{plan.id}")
                pending = client.get(f"/api/v1/companion-requests/{plan.id}", headers=headers(applicant))
                protected = client.get(f"/api/v1/companion-requests/{plan.id}", headers=headers(member))
                owner_detail = client.get(f"/api/v1/companion-requests/{plan.id}", headers=headers(owner))
                mine = client.get("/api/v1/companion-requests/mine", headers=headers(applicant))
                owner_applications = client.get(f"/api/v1/companion-requests/{plan.id}/applications", headers=headers(owner))
            assert listing.status_code == public.status_code == pending.status_code == protected.status_code == owner_detail.status_code == mine.status_code == owner_applications.status_code == 200
            assert listing.json()["items"][0]["id"] == plan.id
            for payload in (public.json(), pending.json()):
                assert {"owner_id", "conversation_id", "itinerary_id", "protected_itinerary"}.isdisjoint(payload)
                assert payload["members"] == []
            assert pending.json()["application_status"] == "pending"
            assert public.json()["viewer_role"] == "public"
            assert pending.json()["viewer_role"] == "applicant"
            assert protected.json()["viewer_role"] == "member"
            assert owner_detail.json()["viewer_role"] == "owner"
            assert protected.json()["itinerary_id"] == itinerary.id and protected.json()["protected_itinerary"] is not None
            assert mine.json()[0]["id"] == plan.id
            assert owner_applications.json()[0]["applicant_display_name"] == "申请人"
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_companion_membership_routes_validate_messages_and_return_acceptance_facts() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="companion-lifecycle-router-test")
        async with sessions() as session:
            owner, applicant = User(phone="13700000031"), User(phone="13700000032")
            session.add_all([owner, applicant])
            await session.flush()
            itinerary = Itinerary(owner_id=owner.id, title="Route", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
            session.add(itinerary)
            await session.flush()
            session.add(ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={
                "title": "Route", "start_date": "2026-10-01", "end_date": "2026-10-01", "days": [{
                    "day_date": "2026-10-01", "display_order": 0, "events": [{
                        "poi_id": "poi-1", "poi_snapshot": {"city": "330100"}, "display_order": 0,
                    }],
                }],
            }))
            plan = CompanionRequest(owner_id=owner.id, itinerary_id=itinerary.id, title="Route", city_code="330100", description="intro", trip_kind="trip", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1), party_size=2, accepted_count=1, travel_pace="slow", interest_tags=["citywalk"], intro_text="intro", review_status="approved", status="open")
            session.add(plan)
            avatar = MediaAsset(owner_id=owner.id, purpose="avatar", mime_type="image/png", size_bytes=1, sha256="a" * 64, object_key="companion-router-group-avatar", status="completed")
            session.add(avatar)
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = lambda user: {"Authorization": f"Bearer {auth.create_access_token(user_id=user.id, audience='consumer', roles=['user'])}"}
        try:
            with TestClient(app) as client:
                assert client.post(f"/api/v1/companion-requests/{plan.id}/applications", headers=headers(applicant), json={"message": "   "}).status_code == 422
                created = client.post(f"/api/v1/companion-requests/{plan.id}/applications", headers=headers(applicant), json={"message": "I would like to join."})
                assert created.status_code == 201
                missing_profile = client.post(f"/api/v1/companion-applications/{created.json()['id']}:accept", headers=headers(owner))
                assert missing_profile.status_code == 422
                assert missing_profile.json()["code"] == "GROUP_NAME_REQUIRED"
                accepted = client.post(
                    f"/api/v1/companion-applications/{created.json()['id']}:accept",
                    headers=headers(owner),
                    json={"group_name": "Weekend walkers", "group_avatar_asset_id": avatar.id},
                )
                assert accepted.status_code == 200
                assert accepted.json()["application"]["status"] == "accepted"
                assert accepted.json()["conversation_id"]
                assert accepted.json()["group_name"] == "Weekend walkers"
                assert accepted.json()["group_avatar_asset_id"] == avatar.id
                assert accepted.json()["plan_status"] == "full"
                left = client.post(f"/api/v1/companion-requests/{plan.id}:leave", headers=headers(applicant))
                assert left.status_code == 200 and left.json()["status"] == "open"
                assert client.post(f"/api/v1/companion-requests/{plan.id}:complete", headers=headers(applicant)).status_code == 403
                assert client.post(f"/api/v1/companion-requests/{plan.id}:complete", headers=headers(owner)).status_code == 200
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_owner_metadata_patch_returns_updated_plan_and_rejects_invalid_body() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="companion-edit-router-test")
        async with sessions() as session:
            owner = User(phone="13700000054")
            session.add(owner)
            await session.flush()
            plan = CompanionRequest(owner_id=owner.id, title="Route", city_code="330100", description="intro", trip_kind="activity", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1), party_size=3, accepted_count=2, travel_pace="slow", interest_tags=["citywalk"], intro_text="intro", review_status="approved", status="open")
            session.add(plan)
            await session.commit()
        app = create_app()
        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = {"Authorization": f"Bearer {auth.create_access_token(user_id=owner.id, audience='consumer', roles=['user'])}"}
        try:
            with TestClient(app) as client:
                updated = client.patch(f"/api/v1/companion-requests/{plan.id}", headers=headers, json={"party_size": 2, "budget_min": 700, "budget_max": 1100, "currency": "CNY", "travel_pace": "packed", "interest_tags": ["food"], "intro_text": "Updated intro"})
                invalid = client.patch(f"/api/v1/companion-requests/{plan.id}", headers=headers, json={"interest_tags": ["unsupported"]})
            assert updated.status_code == 200
            assert updated.json()["party_size"] == 2 and updated.json()["status"] == "full"
            assert updated.json()["intro_text"] == "Updated intro"
            assert invalid.status_code == 422
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_itinerary_companion_workspace_returns_only_current_role_safe_facts() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="companion-workspace-router-test")
        async with sessions() as session:
            owner, editor, member = User(phone="13700000041"), User(phone="13700000042"), User(phone="13700000043")
            session.add_all([owner, editor, member])
            await session.flush()
            itinerary = Itinerary(owner_id=owner.id, title="Route", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
            session.add(itinerary)
            await session.flush()
            session.add_all([
                TripCollaborator(itinerary_id=itinerary.id, user_id=editor.id, role="editor", status="accepted"),
                TripCollaborator(itinerary_id=itinerary.id, user_id=member.id, role="editor", status="accepted"),
            ])
            plan = CompanionRequest(owner_id=owner.id, itinerary_id=itinerary.id, title="Route", city_code="330100", description="intro", trip_kind="trip", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1), party_size=3, accepted_count=2, travel_pace="slow", interest_tags=["citywalk"], intro_text="intro", review_status="approved", status="open", conversation_id="group-1")
            session.add(plan)
            await session.flush()
            session.add(CompanionApplication(request_id=plan.id, applicant_id=member.id, message="join", status="accepted"))
            await session.commit()
        app = create_app()
        async def override_session() -> AsyncIterator[AsyncSession]:
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        headers = lambda user: {"Authorization": f"Bearer {auth.create_access_token(user_id=user.id, audience='consumer', roles=['user'])}"}
        try:
            with TestClient(app) as client:
                owner_response = client.get(f"/api/v1/itineraries/{itinerary.id}/companion-workspace", headers=headers(owner))
                editor_response = client.get(f"/api/v1/itineraries/{itinerary.id}/companion-workspace", headers=headers(editor))
                member_response = client.get(f"/api/v1/itineraries/{itinerary.id}/companion-workspace", headers=headers(member))
            assert owner_response.json() == {"id": plan.id, "status": "open", "review_status": "approved", "party_size": 3, "accepted_count": 2, "role": "owner", "conversation_id": "group-1"}
            assert editor_response.json() == {"id": plan.id, "status": "open", "review_status": None, "party_size": 3, "accepted_count": 2, "role": "collaborator", "conversation_id": None}
            assert member_response.json()["role"] == "member"
            assert member_response.json()["conversation_id"] == "group-1"
        finally:
            await engine.dispose()
    asyncio.run(scenario())
