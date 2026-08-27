import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import CommunityKnowledgeReview
from app.modules.chat.models import ConversationMember
from app.modules.community.models import CompanionApplication, CompanionRequest, Post, PostMedia, PostReaction
from app.modules.community.service import CommunityError, CommunityService
from app.modules.itineraries.models import Itinerary, ItineraryVersion, TripCollaborator
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


@pytest.mark.anyio
async def test_post_reaction_is_idempotent(session):
    user = User(id=str(uuid.uuid4()), phone="13800000000")
    post = Post(id=str(uuid.uuid4()), author_id=user.id, title="A", body_text="B", status="published")
    session.add_all([user, post])
    await session.commit()
    service = CommunityService(session)
    first = await service.react(post.id, user.id)
    second = await service.react(post.id, user.id)
    assert first.id == second.id


@pytest.mark.anyio
async def test_follow_is_idempotent_and_cannot_target_self(session):
    follower, followee = User(phone="13800000015"), User(phone="13800000016")
    session.add_all([follower, followee])
    await session.commit()
    service = CommunityService(session)
    first = await service.follow(follower.id, followee.id)
    second = await service.follow(follower.id, followee.id)
    assert first.id == second.id
    await service.unfollow(follower.id, followee.id)
    await service.unfollow(follower.id, followee.id)
    with pytest.raises(CommunityError, match="SELF_FOLLOW"):
        await service.follow(follower.id, follower.id)


@pytest.mark.anyio
async def test_only_owner_can_submit_draft(session):
    owner, other = User(id=str(uuid.uuid4()), phone="13800000001"), User(id=str(uuid.uuid4()), phone="13800000002")
    post = Post(id=str(uuid.uuid4()), author_id=owner.id, title="A", body_text="B")
    session.add_all([owner, other, post])
    await session.commit()
    with pytest.raises(CommunityError, match="FORBIDDEN"):
        await CommunityService(session).submit_for_review(post.id, other.id)


@pytest.mark.anyio
async def test_post_must_be_pending_before_publication(session):
    owner = User(id=str(uuid.uuid4()), phone="13800000007")
    post = Post(id=str(uuid.uuid4()), author_id=owner.id, title="A", body_text="B")
    session.add_all([owner, post]); await session.commit()
    service = CommunityService(session)
    with pytest.raises(CommunityError, match="INVALID_POST_TRANSITION"):
        await service.publish(post.id, owner.id)
    await service.submit_for_review(post.id, owner.id)
    published = await service.publish(post.id, owner.id, "approved")
    assert published.status == "published"
    await session.commit()

    reviews = list((await session.scalars(select(CommunityKnowledgeReview).where(CommunityKnowledgeReview.post_id == post.id))).all())
    event = await session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "post.published"))

    assert reviews == []
    assert event is not None
    assert event.payload_json == {
        "post_id": post.id,
        "author_id": owner.id,
        "content_type": "note",
        "city_code": None,
    }
    with pytest.raises(CommunityError, match="INVALID_POST_TRANSITION"):
        await service.publish(post.id, owner.id)
    assert not list((await session.scalars(select(CommunityKnowledgeReview).where(CommunityKnowledgeReview.post_id == post.id))).all())


@pytest.mark.anyio
async def test_city_scoped_publication_enqueues_one_community_knowledge_review(session):
    owner = User(phone="13800000017")
    session.add(owner)
    await session.flush()
    post = Post(author_id=owner.id, title="West Lake walk", body_text="Arrive early.", city_code="330100")
    session.add(post)
    await session.commit()
    service = CommunityService(session)

    await service.submit_for_review(post.id, owner.id)
    await service.publish(post.id, owner.id)
    await session.commit()

    reviews = list(
        (await session.scalars(select(CommunityKnowledgeReview).where(CommunityKnowledgeReview.post_id == post.id))).all()
    )
    assert [(review.post_id, review.status) for review in reviews] == [(post.id, "pending")]


@pytest.mark.anyio
async def test_publishing_field_note_preserves_post_outbox_contract_and_queues_optional_review(session):
    author, admin = User(phone="13800000024"), User(phone="13800000025")
    session.add_all([author, admin])
    await session.flush()
    note = Post(
        author_id=author.id,
        content_type="itinerary",
        title="West Lake field note",
        recap_text="Arrive early.",
        city_code="330100",
        status="pending_review",
        itinerary_snapshot_json={"title": "West Lake", "start_date": "2026-10-01", "end_date": "2026-10-01", "days": []},
    )
    session.add(note)
    await session.commit()

    published = await CommunityService(session).publish(note.id, admin.id, "Reviewed route.", is_admin=True)
    await session.commit()

    event = await session.scalar(select(OutboxEvent).where(
        OutboxEvent.aggregate_id == note.id,
        OutboxEvent.event_type == "post.published",
    ))
    review = await session.scalar(select(CommunityKnowledgeReview).where(CommunityKnowledgeReview.post_id == note.id))
    assert published.status == "published"
    assert event is not None
    assert event.payload_json == {
        "post_id": note.id,
        "author_id": author.id,
        "content_type": "itinerary",
        "city_code": "330100",
    }
    assert review is not None and review.status == "pending"


@pytest.mark.anyio
async def test_companion_application_is_idempotent_and_can_be_withdrawn(session):
    owner, applicant = User(phone="13800000008"), User(phone="13800000009")
    session.add_all([owner, applicant]); await session.flush()
    request = CompanionRequest(
        owner_id=owner.id,
        title="West Lake",
        description="Weekend walk",
        party_size=2,
        accepted_count=1,
        review_status="approved",
        status="open",
    )
    session.add(request); await session.commit()
    service = CommunityService(session)
    first = await service.apply_to_companion(request.id, applicant.id, "I would like to join")
    second = await service.apply_to_companion(request.id, applicant.id, "Retry")
    assert first.id == second.id
    withdrawn = await service.withdraw_application(first.id, applicant.id)
    assert withdrawn.status == "withdrawn"
    with pytest.raises(CommunityError, match="INVALID_APPLICATION_TRANSITION"):
        await service.withdraw_application(first.id, applicant.id)


@pytest.mark.anyio
async def test_only_owner_manages_applications_and_acceptance_creates_group(session):
    owner, applicant, outsider = User(phone="13800000010"), User(phone="13800000011"), User(phone="13800000012")
    session.add_all([owner, applicant, outsider]); await session.flush()
    itinerary = Itinerary(
        owner_id=owner.id,
        title="Suzhou itinerary",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
    )
    session.add(itinerary)
    await session.flush()
    request = CompanionRequest(
        owner_id=owner.id,
        itinerary_id=itinerary.id,
        title="Suzhou",
        description="Garden trip",
        party_size=2,
        accepted_count=1,
        review_status="approved",
        status="open",
    )
    session.add(request); await session.flush()
    avatar = MediaAsset(
        owner_id=owner.id,
        purpose="avatar",
        mime_type="image/png",
        size_bytes=1,
        sha256="a" * 64,
        object_key="service-group-avatar",
        status="completed",
    )
    session.add(avatar)
    application = CompanionApplication(request_id=request.id, applicant_id=applicant.id, message="Hello")
    session.add(application); await session.commit()
    service = CommunityService(session)
    with pytest.raises(CommunityError, match="FORBIDDEN"):
        await service.list_request_applications(request.id, outsider.id)
    accepted, conversation = await service.accept_companion_application(
        application.id,
        owner.id,
        group_name="Suzhou walkers",
        group_avatar_asset_id=avatar.id,
    )
    conversation_id = conversation.id
    assert accepted.status == "accepted"
    assert conversation_id is not None
    assert request.status == "full"
    members = list((await session.scalars(__import__("sqlalchemy").select(ConversationMember).where(ConversationMember.conversation_id == conversation_id))).all())
    assert {member.user_id for member in members} == {owner.id, applicant.id}


@pytest.mark.anyio
async def test_only_owner_can_close_or_cancel_open_request(session):
    owner, other = User(phone="13800000013"), User(phone="13800000014")
    session.add_all([owner, other]); await session.flush()
    request = CompanionRequest(owner_id=owner.id, title="Ningbo", description="Seafood", review_status="approved")
    session.add(request); await session.commit()
    service = CommunityService(session)
    with pytest.raises(CommunityError, match="FORBIDDEN"):
        await service.transition_companion_request(request.id, other.id, "closed")
    closed = await service.transition_companion_request(request.id, owner.id, "closed")
    assert closed.status == "closed"
    with pytest.raises(CommunityError, match="INVALID_COMPANION_REQUEST_TRANSITION"):
        await service.transition_companion_request(request.id, owner.id, "cancelled")


@pytest.mark.anyio
@pytest.mark.parametrize("review_status", ["pending_review", "rejected"])
async def test_owner_cannot_transition_or_complete_unreviewed_companion_request(session, review_status):
    owner = User(phone=f"138000000{30 if review_status == 'pending_review' else 31}")
    session.add(owner)
    await session.flush()
    request = CompanionRequest(owner_id=owner.id, title="Unreviewed", description="Hidden", review_status=review_status)
    session.add(request)
    await session.commit()
    service = CommunityService(session)

    for target in ("closed", "cancelled", "open"):
        with pytest.raises(CommunityError, match="INVALID_COMPANION_REQUEST_TRANSITION"):
            await service.transition_companion_request(request.id, owner.id, target)
    with pytest.raises(CommunityError, match="INVALID_COMPANION_REQUEST_TRANSITION"):
        await service.complete_companion_plan(request.id, owner.id)
    assert request.status == "open"


@pytest.mark.anyio
async def test_field_note_editor_freezes_only_public_route_data(session):
    owner, editor = User(phone="13800000018"), User(phone="13800000019")
    session.add_all([owner, editor])
    await session.flush()
    itinerary = Itinerary(owner_id=owner.id, title="Live title", start_date=date(2026, 10, 1), end_date=date(2026, 10, 2))
    session.add(itinerary)
    await session.flush()
    version = ItineraryVersion(
        itinerary_id=itinerary.id,
        version=1,
        created_by=owner.id,
        snapshot={
            "title": "West Lake", "start_date": "2026-10-01", "end_date": "2026-10-02", "budget": {"private": True},
            "destination": {"name": "Hangzhou", "city_code": "330100"},
            "days": [{"id": "private-day", "day_date": "2026-10-01", "display_order": 0, "checklist": ["private"],
                      "events": [{"id": "private-event", "poi_id": "poi-1", "poi_snapshot": {"name": "West Lake"}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": "Morning", "payment": {"private": True}}],
                      "route_segments": [{"route_snapshot": {"secret": True}}], "route_calculation": {"id": "private-job"}}],
        },
    )
    image = MediaAsset(owner_id=editor.id, purpose="field_note", mime_type="image/jpeg", size_bytes=1, sha256="a" * 64, object_key="field-note-image", status="completed")
    collaborator = TripCollaborator(itinerary_id=itinerary.id, user_id=editor.id, role="editor", status="accepted")
    session.add_all([version, image, collaborator])
    await session.commit()

    post = await CommunityService(session).create_field_note(
        editor.id, itinerary.id, version_no=1, title="West Lake slowly", recap_text="Go early.", cover_media_id=image.id, media_ids=[image.id]
    )

    assert post.status == "pending_review"
    assert post.itinerary_snapshot_json == {
        "title": "West Lake", "start_date": "2026-10-01", "end_date": "2026-10-02",
        "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [{"poi_id": "poi-1", "poi_snapshot": {"name": "West Lake"}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": "Morning"}]}],
    }
    media = await session.scalar(select(PostMedia).where(PostMedia.post_id == post.id))
    assert media is not None and media.media_id == image.id and media.sort_order == 0
    assert post.city_code == "330100"


@pytest.mark.anyio
async def test_field_note_rejects_unowned_incomplete_media_and_empty_version(session):
    owner, outsider = User(phone="13800000020"), User(phone="13800000021")
    session.add_all([owner, outsider])
    await session.flush()
    itinerary = Itinerary(owner_id=owner.id, title="Trip", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
    session.add(itinerary)
    await session.flush()
    version = ItineraryVersion(itinerary_id=itinerary.id, version=1, created_by=owner.id, snapshot={"title": "Trip", "start_date": "2026-10-01", "end_date": "2026-10-01", "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [{"poi_id": "poi-1", "poi_snapshot": {}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": None}]}]})
    empty_version = ItineraryVersion(itinerary_id=itinerary.id, version=2, created_by=owner.id, snapshot={"title": "Trip", "start_date": "2026-10-01", "end_date": "2026-10-01", "days": [{"day_date": "2026-10-01", "display_order": 0, "events": []}]})
    other_image = MediaAsset(owner_id=outsider.id, purpose="field_note", mime_type="image/png", size_bytes=1, sha256="b" * 64, object_key="other-image", status="completed")
    pending_image = MediaAsset(owner_id=owner.id, purpose="field_note", mime_type="image/png", size_bytes=1, sha256="c" * 64, object_key="pending-image", status="pending", upload_expires_at=__import__("app.models.base", fromlist=["utc_now"]).utc_now())
    document = MediaAsset(owner_id=owner.id, purpose="field_note", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", size_bytes=1, sha256="d" * 64, object_key="document", status="completed")
    session.add_all([version, empty_version, other_image, pending_image, document])
    await session.commit()
    service = CommunityService(session)

    with pytest.raises(CommunityError, match="FORBIDDEN"):
        await service.create_field_note(owner.id, itinerary.id, version_no=1, title="Trip", recap_text="Recap", cover_media_id=other_image.id, media_ids=[other_image.id])
    with pytest.raises(CommunityError, match="INVALID_FIELD_NOTE_MEDIA"):
        await service.create_field_note(owner.id, itinerary.id, version_no=1, title="Trip", recap_text="Recap", cover_media_id=pending_image.id, media_ids=[pending_image.id])
    with pytest.raises(CommunityError, match="INVALID_FIELD_NOTE_MEDIA"):
        await service.create_field_note(owner.id, itinerary.id, version_no=1, title="Trip", recap_text="Recap", cover_media_id=document.id, media_ids=[document.id])
    with pytest.raises(CommunityError, match="INVALID_FIELD_NOTE_ITINERARY"):
        await service.create_field_note(owner.id, itinerary.id, version_no=2, title="Trip", recap_text="Recap", cover_media_id=pending_image.id, media_ids=[pending_image.id])


@pytest.mark.anyio
async def test_field_note_discovery_is_published_filtered_and_cursor_paginated(session):
    author = User(phone="13800000022")
    session.add(author)
    await session.flush()
    snapshot = {
        "title": "Hangzhou route", "start_date": "2026-10-01", "end_date": "2026-10-01",
        "days": [{"day_date": "2026-10-01", "display_order": 0, "events": [{"poi_id": "poi-1", "poi_snapshot": {}, "starts_at": None, "ends_at": None, "display_order": 0, "notes": None}]}],
    }
    posts = [
        Post(author_id=author.id, content_type="itinerary", title="Older Hangzhou", recap_text="Tea by the lake", city_code="330100", status="published", published_at=__import__("app.models.base", fromlist=["utc_now"]).utc_now(), itinerary_snapshot_json=snapshot),
        Post(author_id=author.id, content_type="itinerary", title="Hidden Hangzhou", recap_text="hidden", city_code="330100", status="pending_review", itinerary_snapshot_json=snapshot),
        Post(author_id=author.id, content_type="note", title="Legacy note", recap_text="Tea by the lake", city_code="330100", status="published"),
    ]
    session.add_all(posts)
    await session.commit()

    service = CommunityService(session)
    items, cursor = await service.list_field_notes(city_code="330100", query="tea", sort="latest", limit=1, cursor=None)
    assert [item.id for item in items] == [posts[0].id]
    assert cursor is None
    assert (await service.field_note_response(items[0])).stop_count == 1


@pytest.mark.anyio
async def test_field_note_detail_requires_published_itinerary(session):
    author = User(phone="13800000023")
    session.add(author)
    await session.flush()
    note = Post(author_id=author.id, content_type="note", title="Note", body_text="Body", status="published")
    pending = Post(author_id=author.id, content_type="itinerary", title="Pending", body_text="", status="pending_review")
    session.add_all([note, pending])
    await session.commit()
    service = CommunityService(session)
    with pytest.raises(CommunityError, match="POST_NOT_FOUND"):
        await service.get_published_field_note(note.id)
    with pytest.raises(CommunityError, match="POST_NOT_FOUND"):
        await service.get_published_field_note(pending.id)
