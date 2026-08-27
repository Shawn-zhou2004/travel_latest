import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.modules.itineraries.service import ItineraryService


async def make_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return AsyncSession(engine, expire_on_commit=False), engine


async def make_users_and_itinerary(session: AsyncSession):
    owner = User(phone="13800000000")
    editor = User(phone="13900000000")
    viewer = User(phone="13700000000")
    session.add_all([owner, editor, viewer])
    await session.commit()
    itinerary = await ItineraryService(session).create_itinerary(
        owner.id, title="Hangzhou", start_date=date(2026, 10, 1), end_date=date(2026, 10, 2)
    )
    return itinerary, owner, editor, viewer


def test_share_token_is_validated_revoked_and_expired() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner, _, _ = await make_users_and_itinerary(session)
            service = ItineraryService(session)
            created = await service.create_share_token(itinerary.id, owner.id, expires_at=None)
            assert created is not None
            share_token, plaintext = created
            assert plaintext != share_token.token_hash
            assert await service.get_shared_itinerary(itinerary.id, plaintext) is not None
            assert await service.get_shared_itinerary(itinerary.id, "wrong-token" * 4) is None
            assert await service.revoke_share_token(itinerary.id, share_token.id, owner.id) is True
            assert await service.get_shared_itinerary(itinerary.id, plaintext) is None
            expired = await service.create_share_token(itinerary.id, owner.id, expires_at=datetime.now(timezone.utc) + timedelta(seconds=1))
            assert expired is not None
            expired[0].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()
            assert await service.get_shared_itinerary(itinerary.id, expired[1]) is None
        finally:
            await session.close()
            await engine.dispose()
    asyncio.run(scenario())


def test_collaborator_roles_enforce_read_edit_and_version_conflicts() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            itinerary, owner, editor, viewer = await make_users_and_itinerary(session)
            service = ItineraryService(session)
            editor_invite = await service.invite_collaborator(itinerary.id, owner.id, user_id=editor.id, role="editor")
            viewer_invite = await service.invite_collaborator(itinerary.id, owner.id, user_id=viewer.id, role="viewer")
            assert editor_invite is not None and viewer_invite is not None
            assert await service.accept_collaborator(itinerary.id, editor_invite.id, editor.id) is not None
            assert (await service.accept_collaborator(itinerary.id, editor_invite.id, editor.id)).status == "accepted"
            assert await service.accept_collaborator(itinerary.id, viewer_invite.id, viewer.id) is not None
            assert await service.get_access_role(itinerary, owner.id) == "owner"
            assert await service.get_access_role(itinerary, editor.id) == "editor"
            assert await service.get_access_role(itinerary, viewer.id) == "viewer"
            denied = await service.apply_operation(itinerary.id, viewer.id, base_version=1, operation_id="viewer-op", operation_type="add_day", payload={"day_date": "2026-10-01"})
            assert denied.code == "FORBIDDEN"
            applied = await service.apply_operation(itinerary.id, editor.id, base_version=1, operation_id="editor-op", operation_type="add_day", payload={"day_date": "2026-10-01"})
            assert applied.code == "APPLIED"
            conflict = await service.apply_operation(itinerary.id, owner.id, base_version=1, operation_id="owner-stale-op", operation_type="add_day", payload={"day_date": "2026-10-02"})
            assert conflict.code == "VERSION_CONFLICT"
            assert conflict.current_version == 2
        finally:
            await session.close()
            await engine.dispose()
    asyncio.run(scenario())
