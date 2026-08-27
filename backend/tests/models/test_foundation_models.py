import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.outbox import OutboxEvent, ProcessedEvent
from app.models.user import User, UserRole, UserSession
from app.modules.chat.models import Conversation
from app.modules.media.models import MediaAsset  # noqa: F401


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as database_session:
        yield database_session

    await engine.dispose()


@pytest.mark.anyio
async def test_user_phone_is_unique(session: AsyncSession) -> None:
    """Removing the phone unique constraint permits duplicate accounts."""
    session.add_all([User(phone="13800138000"), User(phone="13800138000")])

    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.anyio
async def test_conversation_persists_nullable_group_profile(session: AsyncSession) -> None:
    conversation = Conversation(conversation_type="companion_group", title="Weekend walkers", avatar_asset_id=None)
    session.add(conversation)
    await session.commit()
    assert conversation.title == "Weekend walkers"
    assert conversation.avatar_asset_id is None


@pytest.mark.anyio
async def test_role_is_unique_per_user_and_scope(session: AsyncSession) -> None:
    """Removing the user, role, scope unique constraint duplicates authority."""
    user = User(phone="13800138001")
    session.add(user)
    await session.flush()
    first_role = UserRole(user_id=user.id, role="user", scope_key=None)
    second_role = UserRole(user_id=user.id, role="user", scope_key=None)
    assert first_role.scope_key == second_role.scope_key == ""
    session.add_all([first_role, second_role])

    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.anyio
async def test_user_uses_a_uuid_v4_identifier(session: AsyncSession) -> None:
    """Replacing UUID v4 generation breaks externally safe user identities."""
    user = User(phone="13800138002")
    session.add(user)
    await session.commit()

    assert uuid.UUID(user.id).version == 4


@pytest.mark.anyio
async def test_session_persists_only_the_refresh_token_hash(session: AsyncSession) -> None:
    """Replacing refresh_token_hash with raw token storage exposes credentials."""
    user = User(phone="13800138003")
    session.add(user)
    await session.flush()
    session.add(
        UserSession(
            user_id=user.id,
            refresh_token_hash="sha256:9e107d9d372bb6826bd81d3542a419d6",
            expires_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    await session.commit()

    stored_hash = await session.scalar(select(UserSession.refresh_token_hash))
    assert stored_hash == "sha256:9e107d9d372bb6826bd81d3542a419d6"
    assert "refresh_token" not in UserSession.__table__.columns.keys()


@pytest.mark.anyio
async def test_outbox_event_envelope_fields_are_immutable_after_insert(
    session: AsyncSession,
) -> None:
    """Allowing envelope rewrites corrupts the event consumers deduplicate."""
    event = OutboxEvent(
        event_type="itinerary.generated",
        aggregate_type="itinerary",
        aggregate_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        payload_json={"itinerary_id": "itinerary-1", "status": "completed"},
    )
    session.add(event)
    await session.commit()

    with pytest.raises(ValueError):
        event.payload_json = {"itinerary_id": "itinerary-2"}


@pytest.mark.anyio
async def test_outbox_event_payload_cannot_be_mutated_in_place(
    session: AsyncSession,
) -> None:
    """Mutable payloads allow a persisted event envelope to be silently rewritten."""
    event = OutboxEvent(
        event_type="itinerary.generated",
        aggregate_type="itinerary",
        aggregate_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        payload_json={"itinerary_id": "itinerary-1", "status": "completed"},
    )
    session.add(event)
    await session.commit()

    with pytest.raises(TypeError):
        event.payload_json["status"] = "failed"

    await session.refresh(event)
    assert event.payload_json == {"itinerary_id": "itinerary-1", "status": "completed"}


@pytest.mark.anyio
async def test_outbox_event_payload_freezes_mapping_inside_tuple(
    session: AsyncSession,
) -> None:
    """Leaving tuple members unfrozen permits an event payload rewrite."""
    event = OutboxEvent(
        event_type="itinerary.generated",
        aggregate_type="itinerary",
        aggregate_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        payload_json={"items": ({"status": "pending"},)},
    )
    session.add(event)
    await session.commit()

    with pytest.raises(TypeError):
        event.payload_json["items"][0]["status"] = "completed"

    await session.refresh(event)
    assert event.payload_json == {"items": ({"status": "pending"},)}


@pytest.mark.parametrize(
    ("factory", "keyword"),
    [
        (lambda value: User(id=value, phone="13800138004"), "id"),
        (
            lambda value: OutboxEvent(
                event_id=value,
                event_type="itinerary.generated",
                aggregate_type="itinerary",
                aggregate_id=str(uuid.uuid4()),
                trace_id=str(uuid.uuid4()),
                payload_json={"itinerary_id": "itinerary-1", "status": "completed"},
            ),
            "event_id",
        ),
        (
            lambda value: OutboxEvent(
                event_type="itinerary.generated",
                aggregate_type="itinerary",
                aggregate_id=value,
                trace_id=str(uuid.uuid4()),
                payload_json={"itinerary_id": "itinerary-1", "status": "completed"},
            ),
            "aggregate_id",
        ),
        (
            lambda value: OutboxEvent(
                event_type="itinerary.generated",
                aggregate_type="itinerary",
                aggregate_id=str(uuid.uuid4()),
                trace_id=value,
                payload_json={"itinerary_id": "itinerary-1", "status": "completed"},
            ),
            "trace_id",
        ),
    ],
)
def test_model_rejects_invalid_supplied_public_identifier(factory: object, keyword: str) -> None:
    """Accepting non-v4 public identifiers corrupts public-ID contracts before persistence."""
    with pytest.raises(ValueError, match=keyword):
        factory("not-a-uuid")


@pytest.mark.anyio
async def test_processed_event_deduplicates_a_consumer_event_pair(
    session: AsyncSession,
) -> None:
    """Removing consumer/event uniqueness permits duplicate side effects."""
    event_id = str(uuid.uuid4())
    session.add(
        OutboxEvent(
            event_id=event_id,
            event_type="itinerary.generated",
            aggregate_type="itinerary",
            aggregate_id=str(uuid.uuid4()),
            trace_id=str(uuid.uuid4()),
            payload_json={"itinerary_id": "itinerary-1", "status": "completed"},
        )
    )
    await session.flush()
    session.add_all(
        [
            ProcessedEvent(consumer_name="search-indexer", event_id=event_id),
            ProcessedEvent(consumer_name="search-indexer", event_id=event_id),
        ]
    )

    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.anyio
async def test_processed_event_identity_is_immutable_after_insert(
    session: AsyncSession,
) -> None:
    """Allowing processed-event identity changes defeats consumer deduplication."""
    event_id = str(uuid.uuid4())
    session.add(
        OutboxEvent(
            event_id=event_id,
            event_type="itinerary.generated",
            aggregate_type="itinerary",
            aggregate_id=str(uuid.uuid4()),
            trace_id=str(uuid.uuid4()),
            payload_json={"itinerary_id": "itinerary-1", "status": "completed"},
        )
    )
    await session.flush()
    processed_event = ProcessedEvent(
        consumer_name="search-indexer", event_id=event_id
    )
    session.add(processed_event)
    await session.commit()

    with pytest.raises(ValueError):
        processed_event.consumer_name = "notification-worker"
