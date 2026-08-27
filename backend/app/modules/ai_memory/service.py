from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.modules.ai_memory.postgres import AIMemoryRepository


class AIMemoryError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class AIMemoryService:
    def __init__(self, repository: AIMemoryRepository) -> None:
        self._repository = repository

    async def list_conversations(self, user_id: str) -> Sequence[Mapping[str, object]]:
        return await self._repository.list_conversations(user_id)

    async def create_conversation(self, user_id: str, title: str | None) -> Mapping[str, object]:
        conversation_id = await self._repository.create_conversation(user_id, title)
        # A newly inserted conversation is necessarily owned by this consumer.
        conversations = await self._repository.list_conversations(user_id)
        return next(row for row in conversations if str(row["id"]) == conversation_id)

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        return await self._repository.delete_conversation(user_id, conversation_id)

    async def list_messages(self, user_id: str, conversation_id: str) -> Sequence[Mapping[str, object]] | None:
        messages = await self._repository.list_messages(user_id, conversation_id)
        # An empty result is ambiguous, so verify the conversation through an owner-scoped lookup.
        conversations = await self._repository.list_conversations(user_id)
        if not any(str(row["id"]) == conversation_id for row in conversations):
            return None
        return messages

    async def create_message(
        self, user_id: str, conversation_id: str, role: str, content: Mapping[str, object], client_message_id: str | None
    ) -> Mapping[str, object]:
        message = await self._repository.append_message(user_id, conversation_id, role, content, client_message_id)
        if message is None:
            raise AIMemoryError(404, "AI_CONVERSATION_NOT_FOUND", "The AI conversation is unavailable.")
        return message

    async def get_message_by_client_message_id(
        self, user_id: str, conversation_id: str, client_message_id: str
    ) -> Mapping[str, object] | None:
        return await self._repository.get_message_by_client_message_id(user_id, conversation_id, client_message_id)

    async def conversation_exists(self, user_id: str, conversation_id: str) -> bool:
        conversations = await self._repository.list_conversations(user_id)
        return any(str(row["id"]) == conversation_id for row in conversations)

    async def create_assistant_run(
        self, user_id: str, conversation_id: str, client_message_id: str, text: str
    ) -> Mapping[str, object]:
        run = await self._repository.create_assistant_run(user_id, conversation_id, client_message_id, text)
        if run is None:
            raise AIMemoryError(404, "AI_CONVERSATION_NOT_FOUND", "The AI conversation is unavailable.")
        return run

    async def get_assistant_run(self, user_id: str, run_id: str) -> Mapping[str, object] | None:
        return await self._repository.get_assistant_run(user_id, run_id)

    async def start_assistant_run(self, user_id: str, run_id: str) -> Mapping[str, object] | None:
        return await self._repository.start_assistant_run(user_id, run_id)

    async def complete_assistant_run(
        self, user_id: str, run_id: str, source_mode: str, content: Mapping[str, object], assistant_client_message_id: str
    ) -> Mapping[str, object] | None:
        return await self._repository.complete_assistant_run(
            user_id, run_id, source_mode, content, assistant_client_message_id
        )

    async def fail_assistant_run(self, user_id: str, run_id: str, code: str, message: str) -> None:
        await self._repository.fail_assistant_run(user_id, run_id, code, message)

    async def list_memories(self, user_id: str) -> Sequence[Mapping[str, object]]:
        return await self._repository.list_memories(user_id)

    async def create_memory(
        self,
        user_id: str,
        memory_type: str,
        memory_key: str,
        memory_value: Mapping[str, object],
        source: str,
        confidence: float,
    ) -> Mapping[str, object]:
        memory_id = await self._repository.create_memory(
            user_id, memory_type, memory_key, memory_value, source, confidence
        )
        memory = await self._repository.get_memory(user_id, memory_id)
        if memory is None:
            raise RuntimeError("created AI memory is unavailable")
        return memory

    async def sync_travel_profile(
        self, user_id: str, memory_value: Mapping[str, object]
    ) -> Mapping[str, object]:
        return await self._repository.upsert_profile_memory(
            user_id, "travel_profile", memory_value, "user_settings", 1.0
        )

    async def update_memory(
        self, user_id: str, memory_id: str, memory_value: Mapping[str, object], source: str, confidence: float
    ) -> Mapping[str, object] | None:
        return await self._repository.update_memory(user_id, memory_id, memory_value, source, confidence)

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        return await self._repository.delete_memory(user_id, memory_id)
