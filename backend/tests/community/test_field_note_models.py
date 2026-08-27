import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.community.models import Post
from app.modules.itineraries.models import Itinerary, ItineraryCopyOperation
from app.modules.media.models import MediaAsset  # noqa: F401


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
async def test_field_note_columns_allow_legacy_notes_and_require_nonnegative_copy_count(session):
    user = User(id=str(uuid.uuid4()), phone="13800000021")
    legacy = Post(author_id=user.id, content_type="note", title="Legacy", body_text="old")
    session.add_all([user, legacy])
    await session.commit()

    note = Post(
        author_id=user.id,
        content_type="itinerary",
        title="Hangzhou two days",
        body_text="",
        itinerary_snapshot_json={"title": "Hangzhou", "days": []},
        recap_text="Walked before breakfast.",
        copy_count=-1,
    )
    session.add(note)
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.anyio
async def test_copy_operation_enforces_actor_source_idempotency_boundary(session):
    actor = User(id=str(uuid.uuid4()), phone="13800000022")
    author = User(id=str(uuid.uuid4()), phone="13800000023")
    post = Post(author_id=author.id, content_type="itinerary", title="Source", body_text="")
    first_itinerary = Itinerary(
        owner_id=actor.id,
        title="Copied route",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 2),
        source_post_id=post.id,
    )
    second_itinerary = Itinerary(
        owner_id=actor.id,
        title="Duplicate route",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 2),
        source_post_id=post.id,
    )
    session.add_all([actor, author, post, first_itinerary, second_itinerary])
    await session.flush()
    session.add_all(
        [
            ItineraryCopyOperation(actor_id=actor.id, source_post_id=post.id, itinerary_id=first_itinerary.id, idempotency_key="retry-key"),
            ItineraryCopyOperation(actor_id=actor.id, source_post_id=post.id, itinerary_id=second_itinerary.id, idempotency_key="retry-key"),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.commit()
