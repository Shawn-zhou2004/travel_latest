import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User, UserSettings
from app.modules.chat.models import Conversation, ConversationMember, UserBlock
from app.modules.community.models import CompanionApplication, CompanionRequest
from app.modules.community.schemas import CompanionActivityCreate, CompanionPlanCreate
from app.modules.community.service import CommunityError, CommunityService
from app.modules.itineraries.models import Itinerary, ItineraryDay, ItineraryEvent, ItineraryVersion, TripCollaborator
from app.modules.maps.service import MapPOI
from app.modules.media.models import MediaAsset


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as value:
        yield value
    await engine.dispose()


def _plan_body() -> CompanionPlanCreate:
    return CompanionPlanCreate(
        party_size=3, budget_min=600, budget_max=900, currency="CNY", travel_pace="balanced",
        interest_tags=["citywalk", "food"], intro_text="Walk, eat, and keep the pace relaxed.",
    )


@pytest.mark.anyio
async def test_editor_can_publish_plan_from_nonempty_itinerary(session):
    owner = User(id=str(uuid.uuid4()), phone="13700000001")
    editor = User(id=str(uuid.uuid4()), phone="13700000002")
    session.add_all([owner, editor])
    await session.flush()
    itinerary = Itinerary(owner_id=owner.id, title="Live itinerary", start_date=date(2026, 10, 1), end_date=date(2026, 10, 2))
    session.add(itinerary)
    await session.flush()
    session.add_all([
        TripCollaborator(itinerary_id=itinerary.id, user_id=editor.id, role="editor", status="accepted"),
        ItineraryVersion(
            itinerary_id=itinerary.id, version=1, created_by=owner.id,
            snapshot={
                "title": "Hangzhou walk", "start_date": "2026-10-01", "end_date": "2026-10-02",
                "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [
                    {"poi_id": "poi-1", "poi_snapshot": {"name": "West Lake", "city": "330100"}, "display_order": 0},
                ]}],
            },
        ),
    ])
    await session.commit()

    plan = await CommunityService(session).create_companion_plan_from_itinerary(editor.id, itinerary.id, _plan_body())

    assert plan.owner_id == editor.id
    assert plan.title == "Hangzhou walk"
    assert plan.city_code == "330100"
    assert plan.status == "open" and plan.review_status == "pending_review"
    assert plan.accepted_count == 1 and plan.trip_kind == "trip"
    assert plan.start_date == itinerary.start_date and plan.itinerary_id == itinerary.id


@pytest.mark.anyio
async def test_plan_uses_selected_fallback_city_only_when_itinerary_has_no_city(session):
    owner = User(phone="13700000035")
    session.add(owner)
    await session.flush()
    itinerary = Itinerary(owner_id=owner.id, title="Legacy itinerary", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
    session.add(itinerary)
    await session.flush()
    snapshot = {
        "title": "Legacy route", "start_date": "2026-10-01", "end_date": "2026-10-01",
        "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [
            {"poi_id": "poi-1", "poi_snapshot": {"name": "Legacy stop"}, "display_order": 0},
        ]}],
    }
    session.add(ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot=snapshot))
    await session.commit()

    plan = await CommunityService(session).create_companion_plan_from_itinerary(
        owner.id, itinerary.id, _plan_body().model_copy(update={"city_code": "330100"}),
    )

    assert plan.city_code == "330100"
    version = await session.scalar(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id))
    assert plan.itinerary_id == itinerary.id
    assert version is not None and version.snapshot == snapshot


@pytest.mark.anyio
async def test_trusted_itinerary_city_overrides_submitted_fallback(session):
    owner = User(phone="13700000036")
    session.add(owner)
    await session.flush()
    itinerary = Itinerary(owner_id=owner.id, title="Current itinerary", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
    session.add(itinerary)
    await session.flush()
    session.add(ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={
        "title": "Current route", "start_date": "2026-10-01", "end_date": "2026-10-01",
        "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [
            {"poi_id": "poi-1", "poi_snapshot": {"city": "330100"}, "display_order": 0},
        ]}],
    }))
    await session.commit()

    plan = await CommunityService(session).create_companion_plan_from_itinerary(
        owner.id, itinerary.id, _plan_body().model_copy(update={"city_code": "310000"}),
    )

    assert plan.city_code == "330100"


@pytest.mark.anyio
async def test_activity_creation_rolls_back_itinerary_when_plan_validation_fails(session):
    owner = User(id=str(uuid.uuid4()), phone="13700000003")
    session.add(owner)
    await session.commit()
    body = CompanionActivityCreate.model_construct(
        party_size=1, budget_min=None, budget_max=None, currency=None, travel_pace="balanced",
        interest_tags=["citywalk"], intro_text="Walk together.", title="Lake walk", city_code="330100",
        activity_date=date(2026, 10, 1), starts_at=datetime(2026, 10, 1, 9), ends_at=datetime(2026, 10, 1, 11), poi_id="poi-1",
    )

    with pytest.raises(CommunityError, match="INVALID_COMPANION_CAPACITY"):
        await CommunityService(session).create_companion_activity(owner.id, body)

    assert await session.scalar(select(func.count(Itinerary.id))) == 0


@pytest.mark.anyio
async def test_activity_creation_rolls_back_verified_itinerary_when_plan_creation_fails(session, monkeypatch):
    owner = User(id=str(uuid.uuid4()), phone="13700000008")
    session.add(owner)
    await session.commit()

    async def verify_poi(self, poi_id: str):
        return MapPOI(poi_id, "West Lake", "Hangzhou", (120.13, 30.24), city="Hangzhou", adcode="330100")

    async def fail_plan_creation(self, **kwargs):
        raise ValueError("simulated companion plan validation failure")

    monkeypatch.setattr("app.modules.maps.service.AMapService.verify_poi", verify_poi)
    monkeypatch.setattr(CommunityService, "_create_companion_plan", fail_plan_creation)
    body = CompanionActivityCreate(
        party_size=2, travel_pace="slow", interest_tags=["citywalk"], intro_text="An easy lakeside walk.",
        title="West Lake walk", city_code="330100", activity_date=date(2026, 10, 1),
        starts_at=datetime(2026, 10, 1, 9), ends_at=datetime(2026, 10, 1, 11), poi_id="poi-1",
    )

    with pytest.raises(CommunityError, match="INVALID_COMPANION_ACTIVITY"):
        await CommunityService(session).create_companion_activity(owner.id, body)

    assert await session.scalar(select(func.count(Itinerary.id))) == 0
    assert await session.scalar(select(func.count(CompanionRequest.id))) == 0


@pytest.mark.anyio
async def test_activity_creates_verified_one_day_itinerary_and_pending_plan(session, monkeypatch):
    owner = User(id=str(uuid.uuid4()), phone="13700000004")
    session.add(owner)
    await session.commit()

    async def verify_poi(self, poi_id: str):
        return MapPOI(poi_id, "West Lake", "Hangzhou", (120.13, 30.24), city="Hangzhou", adcode="330100")

    monkeypatch.setattr("app.modules.maps.service.AMapService.verify_poi", verify_poi)
    body = CompanionActivityCreate(
        party_size=2, travel_pace="slow", interest_tags=["citywalk"], intro_text="An easy lakeside walk.",
        title="West Lake walk", city_code="330100", activity_date=date(2026, 10, 1),
        starts_at=datetime(2026, 10, 1, 9), ends_at=datetime(2026, 10, 1, 11), poi_id="poi-1",
    )

    plan = await CommunityService(session).create_companion_activity(owner.id, body)
    await session.commit()
    day = await session.scalar(select(ItineraryDay).where(ItineraryDay.itinerary_id == plan.itinerary_id))
    event = await session.scalar(select(ItineraryEvent).where(ItineraryEvent.day_id == day.id))
    version = await session.scalar(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == plan.itinerary_id))

    assert plan.trip_kind == "activity" and plan.review_status == "pending_review"
    assert day.day_date == body.activity_date
    assert event.poi_id == "poi-1" and event.starts_at == body.starts_at and event.ends_at == body.ends_at
    assert version is not None and version.snapshot["days"][0]["events"][0]["poi_id"] == "poi-1"


async def _discovery_plan(session, owner, *, title, start_day, review_status="approved", tags=None):
    itinerary = Itinerary(owner_id=owner.id, title=title, start_date=start_day, end_date=start_day)
    session.add(itinerary)
    await session.flush()
    session.add(ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={
        "title": title, "start_date": start_day.isoformat(), "end_date": start_day.isoformat(), "days": [{
            "day_date": start_day.isoformat(), "display_order": 0, "events": [{
                "poi_id": "poi-1", "poi_snapshot": {"name": "West Lake", "city": "330100"}, "display_order": 0,
                "notes": "private note", "meeting_point": "private meeting point",
            }],
        }],
    }))
    plan = CompanionRequest(owner_id=owner.id, itinerary_id=itinerary.id, title=title, city_code="330100", description="legacy", trip_kind="trip", start_date=start_day, end_date=start_day, party_size=3, accepted_count=1, travel_pace="slow", interest_tags=tags or ["citywalk"], intro_text="Public intro", review_status=review_status, status="open")
    session.add(plan)
    await session.flush()
    return plan


async def _group_avatar(session, owner, object_key):
    asset = MediaAsset(
        owner_id=owner.id, purpose="avatar", mime_type="image/png", size_bytes=1,
        sha256="a" * 64, object_key=object_key, status="completed",
    )
    session.add(asset)
    await session.flush()
    return asset


@pytest.mark.anyio
async def test_public_discovery_filters_before_stable_cursor_pagination(session):
    owner = User(phone="13700000009")
    session.add(owner)
    await session.flush()
    first = await _discovery_plan(session, owner, title="First", start_day=date(2026, 10, 1))
    second = await _discovery_plan(session, owner, title="Second", start_day=date(2026, 10, 2))
    await _discovery_plan(session, owner, title="Pending", start_day=date(2026, 10, 3), review_status="pending_review")
    await _discovery_plan(session, owner, title="Wrong tag", start_day=date(2026, 10, 4), tags=["food"])
    await session.commit()

    service = CommunityService(session)
    first_page = await service.list_public_companion_plans(city_code="330100", start_date=date(2026, 10, 1), end_date=date(2026, 10, 31), trip_kind="trip", travel_pace="slow", tags=["citywalk"], has_slots=True, limit=1, cursor=None)
    second_page = await service.list_public_companion_plans(city_code="330100", start_date=date(2026, 10, 1), end_date=date(2026, 10, 31), trip_kind="trip", travel_pace="slow", tags=["citywalk"], has_slots=True, limit=1, cursor=first_page.next_cursor)

    assert [item.id for item in first_page.items] == [first.id]
    assert [item.id for item in second_page.items] == [second.id]
    assert first_page.next_cursor is not None and second_page.next_cursor is None


@pytest.mark.anyio
async def test_public_and_pending_detail_hide_protected_facts_but_accepted_member_receives_them(session):
    owner = User(phone="13700000010", nickname="Owner")
    pending = User(phone="13700000011")
    accepted = User(phone="13700000012", nickname="Member")
    session.add_all([owner, pending, accepted])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Private route", start_day=date(2026, 10, 1))
    session.add_all([
        CompanionApplication(request_id=plan.id, applicant_id=pending.id, message="private contact", status="pending"),
        CompanionApplication(request_id=plan.id, applicant_id=accepted.id, message="private contact", status="accepted"),
    ])
    await session.commit()

    service = CommunityService(session)
    public = await service.get_companion_plan_detail(plan.id, viewer_id=None)
    applicant = await service.get_companion_plan_detail(plan.id, viewer_id=pending.id)
    member = await service.get_companion_plan_detail(plan.id, viewer_id=accepted.id)
    owner_detail = await service.get_companion_plan_detail(plan.id, viewer_id=owner.id)

    assert public.members == [] and public.conversation_id is None and public.itinerary_id is None and public.protected_itinerary is None
    assert applicant.members == [] and applicant.protected_itinerary is None and applicant.application_status == "pending"
    assert member.itinerary_id == plan.itinerary_id and member.protected_itinerary is not None
    assert public.viewer_role == "public"
    assert applicant.viewer_role == "applicant"
    assert member.viewer_role == "member"
    assert owner_detail.viewer_role == "owner"
    assert "owner_id" not in public.model_dump() and "conversation_id" not in public.model_dump(exclude_none=True)
    assert all("id" not in item.model_dump() for item in member.members)


@pytest.mark.anyio
async def test_companion_member_profiles_respect_private_and_collaborator_visibility(session):
    owner = User(phone="13700000111", nickname="Owner", avatar_asset_id="owner-avatar")
    member = User(phone="13700000112", nickname="Private member", avatar_asset_id="member-avatar")
    session.add_all([owner, member])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Profile visibility", start_day=date(2026, 10, 1))
    session.add_all([
        CompanionApplication(request_id=plan.id, applicant_id=member.id, message="Join", status="accepted"),
        UserSettings(user_id=owner.id, profile_visibility="collaborators"),
        UserSettings(user_id=member.id, profile_visibility="private"),
    ])
    await session.commit()

    service = CommunityService(session)
    owner_detail = await service.get_companion_plan_detail(plan.id, owner.id)
    owner_members = {item.role: item for item in owner_detail.members}
    assert owner_members["owner"].display_name == "Owner"
    assert owner_members["owner"].avatar_asset_id == "owner-avatar"
    assert owner_members["member"].display_name is None
    assert owner_members["member"].avatar_asset_id is None

    member_detail = await service.get_companion_plan_detail(plan.id, member.id)
    member_members = {item.role: item for item in member_detail.members}
    assert member_members["owner"].display_name == "Owner"
    assert member_members["member"].display_name == "Private member"
    assert member_members["member"].avatar_asset_id == "member-avatar"

    settings = await session.get(UserSettings, member.id)
    assert settings is not None
    settings.profile_visibility = "collaborators"
    await session.commit()

    collaborator_detail = await service.get_companion_plan_detail(plan.id, owner.id)
    visible_member = next(item for item in collaborator_detail.members if item.role == "member")
    assert visible_member.display_name == "Private member"
    assert visible_member.avatar_asset_id == "member-avatar"


@pytest.mark.anyio
async def test_mine_includes_owned_accepted_and_pending_but_not_rejected_plans(session):
    viewer, other = User(phone="13700000013"), User(phone="13700000014")
    session.add_all([viewer, other])
    await session.flush()
    owned = await _discovery_plan(session, viewer, title="Owned", start_day=date(2026, 10, 1))
    pending = await _discovery_plan(session, other, title="Pending", start_day=date(2026, 10, 2))
    accepted = await _discovery_plan(session, other, title="Accepted", start_day=date(2026, 10, 3))
    rejected = await _discovery_plan(session, other, title="Rejected", start_day=date(2026, 10, 4))
    session.add_all([
        CompanionApplication(request_id=pending.id, applicant_id=viewer.id, message="join", status="pending"),
        CompanionApplication(request_id=accepted.id, applicant_id=viewer.id, message="join", status="accepted"),
        CompanionApplication(request_id=rejected.id, applicant_id=viewer.id, message="join", status="rejected"),
    ])
    await session.commit()

    assert {item.id for item in await CommunityService(session).list_my_companion_plans(viewer.id)} == {owned.id, pending.id, accepted.id}


@pytest.mark.anyio
async def test_application_is_idempotent_while_active_and_self_application_stays_blocked(session):
    owner, applicant = User(phone="13700000120"), User(phone="13700000121")
    session.add_all([owner, applicant])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Apply once", start_day=date(2026, 10, 1))
    await session.commit()
    service = CommunityService(session)

    with pytest.raises(CommunityError, match="SELF_APPLICATION"):
        await service.apply_to_companion(plan.id, owner.id, "My own plan")

    created = await service.apply_to_companion(plan.id, applicant.id, "First message")
    repeated = await service.apply_to_companion(plan.id, applicant.id, "Ignored replacement")
    await session.flush()

    assert repeated.id == created.id
    assert repeated.status == "pending"
    assert repeated.message == "First message"
    created.status = "accepted"
    accepted_repeat = await service.apply_to_companion(plan.id, applicant.id, "Also ignored")
    assert accepted_repeat.id == created.id
    assert accepted_repeat.status == "accepted"
    assert accepted_repeat.message == "First message"
    events = list((await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == "companion_application.created",
        OutboxEvent.aggregate_id == created.id,
    ))).all())
    assert len(events) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("previous_status", ["withdrawn", "rejected"])
async def test_terminal_application_can_reapply_with_fresh_message_and_event(session, previous_status):
    owner, applicant = User(phone=f"1370000013{0 if previous_status == 'withdrawn' else 1}"), User(phone=f"1370000014{0 if previous_status == 'withdrawn' else 1}")
    session.add_all([owner, applicant])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Apply again", start_day=date(2026, 10, 1))
    application = CompanionApplication(
        request_id=plan.id,
        applicant_id=applicant.id,
        message="Old message",
        status=previous_status,
        conversation_id=str(uuid.uuid4()),
    )
    session.add(application)
    await session.commit()

    reapplied = await CommunityService(session).apply_to_companion(plan.id, applicant.id, "A new reason to join")
    await session.flush()

    assert reapplied.id == application.id
    assert reapplied.status == "pending"
    assert reapplied.message == "A new reason to join"
    assert reapplied.conversation_id is None
    event = await session.scalar(select(OutboxEvent).where(
        OutboxEvent.event_type == "companion_application.created",
        OutboxEvent.aggregate_id == application.id,
    ))
    assert event is not None
    assert event.payload_json["request_id"] == plan.id


@pytest.mark.anyio
async def test_acceptance_grants_editor_group_membership_and_capacity_atomically(session):
    owner, applicant = User(phone="13700000020"), User(phone="13700000021")
    session.add_all([owner, applicant])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Atomic group", start_day=date(2026, 10, 1))
    plan.party_size = 2
    avatar = await _group_avatar(session, owner, "atomic-group-avatar")
    application = CompanionApplication(request_id=plan.id, applicant_id=applicant.id, message="I would like to join.")
    session.add(application)
    await session.commit()

    accepted, conversation = await CommunityService(session).accept_companion_application(
        application.id, owner.id, group_name="  Weekend walkers  ", group_avatar_asset_id=avatar.id,
    )

    collaborator = await session.scalar(select(TripCollaborator).where(
        TripCollaborator.itinerary_id == plan.itinerary_id,
        TripCollaborator.user_id == applicant.id,
    ))
    member_ids = set((await session.scalars(select(ConversationMember.user_id).where(
        ConversationMember.conversation_id == conversation.id,
        ConversationMember.left_at.is_(None),
    ))).all())
    assert accepted.status == "accepted"
    assert accepted.conversation_id == conversation.id == plan.conversation_id
    assert conversation.title == "Weekend walkers" and conversation.avatar_asset_id == avatar.id
    assert collaborator is not None and collaborator.role == "editor" and collaborator.status == "accepted"
    assert member_ids == {owner.id, applicant.id}
    assert plan.accepted_count == plan.party_size and plan.status == "full"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("group_name", "avatar", "error_code"),
    [(None, True, "GROUP_NAME_REQUIRED"), ("Weekend walkers", False, "GROUP_AVATAR_REQUIRED")],
)
async def test_first_acceptance_requires_complete_group_profile_without_side_effects(session, group_name, avatar, error_code):
    owner, applicant = User(phone=f"1370000020{1 if avatar else 2}"), User(phone=f"1370000021{1 if avatar else 2}")
    session.add_all([owner, applicant])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Profile required", start_day=date(2026, 10, 1))
    asset = await _group_avatar(session, owner, f"required-avatar-{error_code}")
    application = CompanionApplication(request_id=plan.id, applicant_id=applicant.id, message="Join")
    session.add(application)
    await session.commit()

    with pytest.raises(CommunityError, match=error_code):
        await CommunityService(session).accept_companion_application(
            application.id, owner.id, group_name=group_name,
            group_avatar_asset_id=asset.id if avatar else None,
        )

    await session.refresh(application)
    await session.refresh(plan)
    assert application.status == "pending" and application.conversation_id is None
    assert plan.conversation_id is None and plan.accepted_count == 1
    assert await session.scalar(select(func.count(Conversation.id))) == 0


@pytest.mark.anyio
async def test_acceptance_checks_review_capacity_and_all_current_member_blocks_without_side_effects(session):
    owner, first_member, applicant = User(phone="13700000022"), User(phone="13700000023"), User(phone="13700000024")
    session.add_all([owner, first_member, applicant])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Blocked group", start_day=date(2026, 10, 1))
    accepted = CompanionApplication(request_id=plan.id, applicant_id=first_member.id, message="Already accepted", status="accepted")
    pending = CompanionApplication(request_id=plan.id, applicant_id=applicant.id, message="Please accept")
    session.add_all([accepted, pending, UserBlock(blocker_id=first_member.id, blocked_id=applicant.id)])
    await session.commit()

    with pytest.raises(CommunityError, match="USER_BLOCKED"):
        await CommunityService(session).accept_companion_application(pending.id, owner.id)

    assert pending.status == "pending"
    assert plan.conversation_id is None
    assert await session.scalar(select(Conversation).where(Conversation.title == plan.title)) is None
    plan.review_status = "pending_review"
    with pytest.raises(CommunityError, match="COMPANION_REQUEST_UNAVAILABLE"):
        await CommunityService(session).accept_companion_application(pending.id, owner.id)


@pytest.mark.anyio
async def test_leave_and_removal_revoke_access_and_reopen_capacity(session):
    owner, first_member, second_member = User(phone="13700000025"), User(phone="13700000026"), User(phone="13700000027")
    session.add_all([owner, first_member, second_member])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Capacity lifecycle", start_day=date(2026, 10, 1))
    plan.party_size = 3
    avatar = await _group_avatar(session, owner, "capacity-group-avatar")
    first = CompanionApplication(request_id=plan.id, applicant_id=first_member.id, message="First")
    second = CompanionApplication(request_id=plan.id, applicant_id=second_member.id, message="Second")
    session.add_all([first, second])
    await session.commit()
    service = CommunityService(session)
    _, conversation = await service.accept_companion_application(
        first.id, owner.id, group_name="Capacity group", group_avatar_asset_id=avatar.id,
    )
    _, reused_conversation = await service.accept_companion_application(second.id, owner.id)
    assert reused_conversation.id == conversation.id
    assert await session.scalar(select(func.count(Conversation.id))) == 1
    assert plan.status == "full"

    await service.leave_companion_plan(plan.id, first_member.id)
    first_collaborator = await session.scalar(select(TripCollaborator).where(
        TripCollaborator.itinerary_id == plan.itinerary_id, TripCollaborator.user_id == first_member.id,
    ))
    assert plan.status == "open" and plan.accepted_count == 2
    assert first.status == "withdrawn" and first_collaborator is not None and first_collaborator.status == "revoked"
    former_member_detail = await service.get_companion_plan_detail(plan.id, viewer_id=first_member.id)
    assert former_member_detail.protected_itinerary is None and former_member_detail.itinerary_id is None

    await service.remove_companion_member(plan.id, owner.id, second_member.id)
    second_collaborator = await session.scalar(select(TripCollaborator).where(
        TripCollaborator.itinerary_id == plan.itinerary_id, TripCollaborator.user_id == second_member.id,
    ))
    assert plan.accepted_count == 1 and second.status == "rejected"
    assert second_collaborator is not None and second_collaborator.status == "revoked"


@pytest.mark.anyio
async def test_completion_revokes_non_owner_editors_and_blocks_future_applications(session):
    owner, member, applicant = User(phone="13700000028"), User(phone="13700000029"), User(phone="13700000030")
    session.add_all([owner, member, applicant])
    await session.flush()
    plan = await _discovery_plan(session, owner, title="Completed", start_day=date(2026, 10, 1))
    accepted = CompanionApplication(request_id=plan.id, applicant_id=member.id, message="Join")
    avatar = await _group_avatar(session, owner, "completed-group-avatar")
    session.add(accepted)
    await session.commit()
    service = CommunityService(session)
    await service.accept_companion_application(
        accepted.id, owner.id, group_name="Completed group", group_avatar_asset_id=avatar.id,
    )
    await service.complete_companion_plan(plan.id, owner.id)

    collaborator = await session.scalar(select(TripCollaborator).where(
        TripCollaborator.itinerary_id == plan.itinerary_id, TripCollaborator.user_id == member.id,
    ))
    assert plan.status == "completed" and collaborator is not None and collaborator.status == "revoked"
    with pytest.raises(CommunityError, match="COMPANION_REQUEST_UNAVAILABLE"):
        await service.apply_to_companion(plan.id, applicant.id, "Too late")
