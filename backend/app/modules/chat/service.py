from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.modules.chat.models import Conversation, ConversationMember, Message, UserBlock
from app.modules.community.models import CompanionRequest


class ChatError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def open_direct(self, actor_id: str, other_user_id: str) -> Conversation:
        if actor_id == other_user_id:
            raise ChatError("INVALID_DIRECT_CONVERSATION", "A direct conversation needs two different users.")
        blocked = await self.session.scalar(select(UserBlock.id).where(or_((UserBlock.blocker_id == actor_id) & (UserBlock.blocked_id == other_user_id), (UserBlock.blocker_id == other_user_id) & (UserBlock.blocked_id == actor_id))))
        if blocked:
            raise ChatError("USER_BLOCKED", "A block prevents new direct contact.")
        direct_key = ":".join(sorted((actor_id, other_user_id)))
        existing = await self.session.scalar(select(Conversation).where(Conversation.direct_key == direct_key))
        if existing:
            return existing
        conversation = Conversation(conversation_type="direct", direct_key=direct_key)
        self.session.add(conversation)
        await self.session.flush()
        self.session.add_all([ConversationMember(conversation_id=conversation.id, user_id=actor_id, joined_at=utc_now()), ConversationMember(conversation_id=conversation.id, user_id=other_user_id, joined_at=utc_now())])
        return conversation

    async def create_message(self, conversation_id: str, sender_id: str, client_message_id: str, message_type: str, body_text: str | None = None, payload_json: dict[str, object] | None = None) -> Message:
        existing = await self.session.scalar(select(Message).where(Message.conversation_id == conversation_id, Message.sender_id == sender_id, Message.client_message_id == client_message_id))
        if existing:
            return existing
        member = await self.session.scalar(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == sender_id, ConversationMember.left_at.is_(None)))
        if member is None:
            raise ChatError("NOT_CONVERSATION_MEMBER", "You cannot send to this conversation.")
        conversation = await self.session.get(Conversation, conversation_id)
        if conversation is None:
            raise ChatError("CONVERSATION_NOT_FOUND", "The conversation does not exist.")
        if conversation.conversation_type == "companion_group":
            plan = await self.session.scalar(
                select(CompanionRequest).where(CompanionRequest.conversation_id == conversation_id)
            )
            if plan is not None and plan.status == "completed":
                raise ChatError(
                    "COMPANION_PLAN_COMPLETED",
                    "This companion plan has ended; group history remains available.",
                )
        if conversation.conversation_type == "direct":
            recipient_id = await self.session.scalar(select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id != sender_id,
                ConversationMember.left_at.is_(None),
            ))
            if recipient_id and await self._is_blocked(sender_id, recipient_id):
                raise ChatError("USER_BLOCKED", "A block prevents new direct messages.")
        message = Message(conversation_id=conversation_id, sender_id=sender_id, client_message_id=client_message_id, message_type=message_type, body_text=body_text, payload_json=payload_json)
        self.session.add(message)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            original = await self.session.scalar(select(Message).where(Message.conversation_id == conversation_id, Message.sender_id == sender_id, Message.client_message_id == client_message_id))
            if original:
                return original
            raise
        recipient_ids = list((await self.session.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id != sender_id, ConversationMember.left_at.is_(None)))).all())
        self.session.add(OutboxEvent(event_type="message.created", aggregate_type="conversation", aggregate_id=conversation_id, trace_id=new_uuid(), payload_json={"conversation_id": conversation_id, "message_id": message.id, "recipient_ids": recipient_ids}))
        return message

    async def block(self, blocker_id: str, blocked_id: str) -> UserBlock:
        if blocker_id == blocked_id:
            raise ChatError("INVALID_BLOCK", "You cannot block yourself.")
        existing = await self.session.scalar(select(UserBlock).where(UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id))
        if existing:
            return existing
        block = UserBlock(blocker_id=blocker_id, blocked_id=blocked_id)
        self.session.add(block)
        await self.session.flush()
        return block

    async def unblock(self, blocker_id: str, blocked_id: str) -> bool:
        block = await self.session.scalar(select(UserBlock).where(UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id))
        if block is None:
            return False
        await self.session.delete(block)
        return True

    async def list_conversations(self, user_id: str, cursor: str | None = None, limit: int | None = 20, conversation_type: str | None = None) -> tuple[list[tuple[Conversation, int, Message | None]], str | None]:
        memberships = select(ConversationMember.conversation_id).where(ConversationMember.user_id == user_id, ConversationMember.left_at.is_(None))
        statement = select(Conversation).where(Conversation.id.in_(memberships))
        if conversation_type is not None:
            statement = statement.where(Conversation.conversation_type == conversation_type)
        statement = statement.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        if limit is not None:
            statement = statement.limit(limit + 1)
        if cursor:
            cursor_conversation = await self.session.get(Conversation, cursor)
            if cursor_conversation:
                statement = statement.where(or_(Conversation.updated_at < cursor_conversation.updated_at, and_(Conversation.updated_at == cursor_conversation.updated_at, Conversation.id < cursor_conversation.id)))
        conversations = list((await self.session.scalars(statement)).all())
        next_cursor = conversations[limit - 1].id if limit is not None and len(conversations) > limit else None
        rows: list[tuple[Conversation, int, Message | None]] = []
        for conversation in conversations[:limit] if limit is not None else conversations:
            member = await self.session.scalar(select(ConversationMember).where(ConversationMember.conversation_id == conversation.id, ConversationMember.user_id == user_id))
            last_message = await self.session.scalar(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc(), Message.id.desc()).limit(1))
            last_read = await self.session.get(Message, member.last_read_message_id) if member and member.last_read_message_id else None
            unread_after = last_read.created_at if last_read else (member.joined_at if member else conversation.created_at)
            unread = await self.session.scalar(select(func.count(Message.id)).where(
                Message.conversation_id == conversation.id,
                Message.sender_id != user_id,
                Message.created_at > unread_after,
            ))
            rows.append((conversation, int(unread or 0), last_message))
        return rows, next_cursor

    async def unread_count(self, user_id: str) -> int:
        members = list((await self.session.scalars(select(ConversationMember).where(
            ConversationMember.user_id == user_id, ConversationMember.left_at.is_(None)
        ))).all())
        total = 0
        for member in members:
            last_read = await self.session.get(Message, member.last_read_message_id) if member.last_read_message_id else None
            unread_after = last_read.created_at if last_read else member.joined_at
            total += int(await self.session.scalar(select(func.count(Message.id)).where(
                Message.conversation_id == member.conversation_id,
                Message.sender_id != user_id,
                Message.created_at > unread_after,
            )) or 0)
        return total

    async def list_messages(self, conversation_id: str, user_id: str, cursor: str | None = None, limit: int = 50) -> tuple[list[Message], str | None]:
        member = await self.session.scalar(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == user_id, ConversationMember.left_at.is_(None)))
        if member is None:
            raise ChatError("NOT_CONVERSATION_MEMBER", "You cannot access this conversation.")
        statement = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc(), Message.id.asc()).limit(limit + 1)
        if cursor:
            cursor_message = await self.session.get(Message, cursor)
            if cursor_message and cursor_message.conversation_id == conversation_id:
                statement = statement.where(or_(Message.created_at > cursor_message.created_at, and_(Message.created_at == cursor_message.created_at, Message.id > cursor_message.id)))
        messages = list((await self.session.scalars(statement)).all())
        next_cursor = messages[limit - 1].id if len(messages) > limit else None
        visible = messages[:limit]
        if visible:
            latest = await self.session.scalar(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.desc(), Message.id.desc()).limit(1)
            )
            member.last_read_message_id = latest.id if latest else visible[-1].id
        return visible, next_cursor

    async def leave_conversation(self, conversation_id: str, user_id: str) -> bool:
        member = await self.session.scalar(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == user_id, ConversationMember.left_at.is_(None)))
        if member is None:
            raise ChatError("NOT_CONVERSATION_MEMBER", "You cannot leave this conversation.")
        member.left_at = utc_now()
        return True

    async def _is_blocked(self, first_user_id: str, second_user_id: str) -> bool:
        return await self.session.scalar(select(UserBlock.id).where(or_(
            and_(UserBlock.blocker_id == first_user_id, UserBlock.blocked_id == second_user_id),
            and_(UserBlock.blocker_id == second_user_id, UserBlock.blocked_id == first_user_id),
        ))) is not None
