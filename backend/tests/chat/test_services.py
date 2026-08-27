import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base, utc_now
from app.models.user import User
from app.modules.chat.models import Conversation, ConversationMember
from app.modules.chat.service import ChatError, ChatService
from app.modules.community.models import CompanionRequest
from app.modules.itineraries.models import Itinerary, ItineraryVersion  # noqa: F401
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
async def test_repeated_client_message_id_returns_original(session):
    a, b = User(id=str(uuid.uuid4()), phone="13800000003"), User(id=str(uuid.uuid4()), phone="13800000004")
    session.add_all([a, b]); await session.commit()
    service = ChatService(session)
    conversation = await service.open_direct(a.id, b.id)
    first = await service.create_message(conversation.id, a.id, "m-1", "text", "hello")
    second = await service.create_message(conversation.id, a.id, "m-1", "text", "hello")
    assert first.id == second.id


@pytest.mark.anyio
async def test_block_prevents_new_direct_contact(session):
    a, b = User(id=str(uuid.uuid4()), phone="13800000005"), User(id=str(uuid.uuid4()), phone="13800000006")
    session.add_all([a, b]); await session.commit()
    service = ChatService(session)
    await service.block(a.id, b.id)
    with pytest.raises(ChatError, match="USER_BLOCKED"):
        await service.open_direct(b.id, a.id)


@pytest.mark.anyio
async def test_block_prevents_new_messages_but_history_remains_readable(session):
    a, b = User(phone="13800000015"), User(phone="13800000016")
    session.add_all([a, b]); await session.flush()
    service = ChatService(session)
    conversation = await service.open_direct(a.id, b.id)
    first = await service.create_message(conversation.id, a.id, "before-block", "text", "before")
    await service.block(a.id, b.id)
    with pytest.raises(ChatError, match="USER_BLOCKED"):
        await service.create_message(conversation.id, b.id, "after-block", "text", "after")
    messages, next_cursor = await service.list_messages(conversation.id, b.id)
    assert [message.id for message in messages] == [first.id]
    assert next_cursor is None


@pytest.mark.anyio
async def test_non_member_cannot_send_and_messages_use_stable_cursor_pagination(session):
    a, b, outsider = User(phone="13800000017"), User(phone="13800000018"), User(phone="13800000019")
    session.add_all([a, b, outsider]); await session.flush()
    service = ChatService(session)
    conversation = await service.open_direct(a.id, b.id)
    with pytest.raises(ChatError, match="NOT_CONVERSATION_MEMBER"):
        await service.create_message(conversation.id, outsider.id, "forbidden", "text", "no")
    sent = [await service.create_message(conversation.id, a.id, f"m-{index}", "text", str(index)) for index in range(3)]
    page_one, cursor = await service.list_messages(conversation.id, b.id, limit=2)
    page_two, next_cursor = await service.list_messages(conversation.id, b.id, cursor=cursor, limit=2)
    assert [message.id for message in page_one] == [sent[0].id, sent[1].id]
    assert [message.id for message in page_two] == [sent[2].id]
    assert next_cursor is None


@pytest.mark.anyio
async def test_completed_companion_group_keeps_history_readable_and_blocks_sends(session):
    owner, member = User(phone="13800000020"), User(phone="13800000021")
    session.add_all([owner, member])
    await session.flush()
    conversation = Conversation(conversation_type="companion_group", title="Lake walk")
    session.add(conversation)
    await session.flush()
    session.add_all([
        ConversationMember(conversation_id=conversation.id, user_id=owner.id, joined_at=utc_now()),
        ConversationMember(conversation_id=conversation.id, user_id=member.id, joined_at=utc_now()),
    ])
    plan = CompanionRequest(
        owner_id=owner.id,
        title="Lake walk",
        description="A companion plan.",
        status="open",
        conversation_id=conversation.id,
    )
    session.add(plan)
    await session.flush()
    service = ChatService(session)
    historic_message = await service.create_message(conversation.id, owner.id, "historic", "text", "Before completion")
    plan.status = "completed"
    messages, next_cursor = await service.list_messages(conversation.id, member.id)
    assert [message.id for message in messages] == [historic_message.id]
    assert next_cursor is None
    with pytest.raises(ChatError, match="COMPANION_PLAN_COMPLETED"):
        await service.create_message(conversation.id, member.id, "after-completion", "text", "Still there?")
