from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.modules.ai_memory.router import _citation_fallback_answer, ask_assistant, get_ai_memory_service, router
from app.modules.ai_memory.schemas import AssistantAskRequest
from app.modules.ai_entitlements.service import AIEntitlementError
from app.modules.auth.dependencies import current_consumer_claims
from app.modules.auth.service import AccessClaims


class FakeService:
    def __init__(self) -> None:
        self.owner_ids: list[str] = []
        self.now = datetime.now(UTC)

    async def list_conversations(self, user_id: str):
        self.owner_ids.append(user_id)
        return [{"id": "conversation-1", "title": "Japan", "created_at": self.now, "updated_at": self.now}]

    async def create_conversation(self, user_id: str, title: str | None):
        self.owner_ids.append(user_id)
        return {"id": "conversation-2", "title": title, "created_at": self.now, "updated_at": self.now}

    async def delete_conversation(self, user_id: str, conversation_id: str):
        self.owner_ids.append(user_id)
        return conversation_id == "conversation-1"

    async def list_messages(self, user_id: str, conversation_id: str):
        self.owner_ids.append(user_id)
        return [] if conversation_id == "conversation-1" else None

    async def create_message(self, user_id: str, conversation_id: str, role: str, content: dict[str, object], client_message_id: str | None):
        self.owner_ids.append(user_id)
        if conversation_id != "conversation-1":
            from app.modules.ai_memory.service import AIMemoryError
            raise AIMemoryError(404, "AI_CONVERSATION_NOT_FOUND", "The AI conversation is unavailable.")
        return {"id": "message-1", "role": role, "content": content, "client_message_id": client_message_id, "created_at": self.now}

    async def conversation_exists(self, user_id: str, conversation_id: str) -> bool:
        return conversation_id == "conversation-1"

    async def get_message_by_client_message_id(self, user_id: str, conversation_id: str, client_message_id: str):
        return None

    async def list_memories(self, user_id: str):
        self.owner_ids.append(user_id)
        return [{
            "id": "memory-1", "memory_type": "profile", "memory_key": "diet",
            "memory_value": {"preference": "vegetarian"}, "source": "user", "confidence": 1.0,
            "created_at": self.now, "updated_at": self.now,
        }]

    async def create_memory(self, user_id: str, memory_type: str, memory_key: str, memory_value: dict[str, object], source: str, confidence: float):
        self.owner_ids.append(user_id)
        return {
            "id": "memory-2", "memory_type": memory_type, "memory_key": memory_key,
            "memory_value": memory_value, "source": source, "confidence": confidence,
            "created_at": self.now, "updated_at": self.now,
        }

    async def update_memory(self, user_id: str, memory_id: str, memory_value: dict[str, object], source: str, confidence: float):
        self.owner_ids.append(user_id)
        if memory_id != "memory-1":
            return None
        return {
            "id": memory_id, "memory_type": "profile", "memory_key": "diet", "memory_value": memory_value,
            "source": source, "confidence": confidence, "created_at": self.now, "updated_at": self.now,
        }

    async def delete_memory(self, user_id: str, memory_id: str):
        self.owner_ids.append(user_id)
        return memory_id == "memory-1"


@pytest.fixture
def client_and_service():
    app = FastAPI()
    app.include_router(router)
    service = FakeService()
    app.dependency_overrides[get_ai_memory_service] = lambda: service
    app.dependency_overrides[current_consumer_claims] = lambda: AccessClaims("owner-1", "session-1", "consumer", ["consumer"])
    with TestClient(app) as client:
        yield client, service


def test_conversation_and_message_routes_use_current_consumer(client_and_service) -> None:
    client, service = client_and_service

    listed = client.get("/ai/conversations")
    created = client.post("/ai/conversations", json={"title": "Japan"})
    message = client.post("/ai/conversations/conversation-1/messages", json={
        "role": "user", "content": {"text": "Plan my trip"}, "client_message_id": "client-1",
    })

    assert listed.status_code == 200
    assert created.status_code == 201
    assert message.status_code == 201
    assert message.json()["role"] == "user"
    assert service.owner_ids == ["owner-1", "owner-1", "owner-1"]


def test_memory_routes_and_owner_scoped_not_found(client_and_service) -> None:
    client, service = client_and_service

    listed = client.get("/ai/memories")
    created = client.post("/ai/memories", json={
        "memory_type": "profile", "memory_key": "diet", "memory_value": {"preference": "vegan"},
        "source": "user", "confidence": 0.9,
    })
    updated = client.patch("/ai/memories/memory-1", json={
        "memory_value": {"preference": "vegan"}, "source": "user", "confidence": 0.9,
    })
    missing = client.delete("/ai/memories/other-memory")

    assert listed.status_code == 200
    assert created.status_code == 201
    assert created.json()["id"] == "memory-2"
    assert updated.status_code == 200
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "AI_MEMORY_NOT_FOUND"
    assert service.owner_ids == ["owner-1", "owner-1", "owner-1", "owner-1"]


def test_conversation_delete_is_owner_scoped(client_and_service) -> None:
    client, service = client_and_service

    deleted = client.delete("/ai/conversations/conversation-1")
    missing = client.delete("/ai/conversations/other")

    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "AI_CONVERSATION_NOT_FOUND"
    assert service.owner_ids == ["owner-1", "owner-1"]


def test_message_role_cannot_impersonate_assistant(client_and_service) -> None:
    client, _ = client_and_service

    response = client.post("/ai/conversations/conversation-1/messages", json={
        "role": "assistant", "content": {"text": "fabricated"},
    })

    assert response.status_code == 422


def test_conversation_response_converts_postgres_uuid_identifiers(client_and_service) -> None:
    client, service = client_and_service
    identifier = uuid4()

    async def create_conversation(user_id: str, title: str | None):
        service.owner_ids.append(user_id)
        return {"id": identifier, "title": title, "created_at": service.now, "updated_at": service.now}

    service.create_conversation = create_conversation
    response = client.post("/ai/conversations", json={"title": "UUID conversation"})

    assert response.status_code == 201
    assert response.json()["id"] == str(identifier)


def test_citation_fallback_answer_returns_retrieved_travel_evidence() -> None:
    answer = _citation_fallback_answer([
        {"content": "洪江古商城位于怀化，是一处保存较完整的明清古城。"},
        {"content": "黔阳古城可安排古城漫步。"},
    ])

    assert "洪江古商城" in answer
    assert "黔阳古城" in answer


def test_agent_kind_classification_reflects_tool_trace() -> None:
    from app.modules.ai_memory.agent import AssistantAgentContext, classify_answer

    assert classify_answer(AssistantAgentContext(user_id="u", settings=object())) == "general"
    official = AssistantAgentContext(user_id="u", settings=object())
    official.tool_trace.append("official_rag")
    assert classify_answer(official) == "source_backed"
    live = AssistantAgentContext(user_id="u", settings=object())
    live.tool_trace.extend(["official_rag", "web_search"])
    assert classify_answer(live) == "live_web"
    weather = AssistantAgentContext(user_id="u", settings=object())
    weather.tool_trace.extend(["official_rag", "weather"])
    assert classify_answer(weather) == "live_web"


def test_agent_rag_tool_formatting_collects_citations_in_order() -> None:
    from types import SimpleNamespace

    from app.modules.ai_memory.agent import AssistantAgentContext, _format_rag_contexts
    from app.modules.ai_rag.types import RagStatus

    citation = SimpleNamespace(
        document_id="doc-1", chunk_id="chunk-1", source_type=SimpleNamespace(value="official"),
        source_id="source-1", city_code="CS",
    )
    result = SimpleNamespace(status=RagStatus.AVAILABLE, contexts=[SimpleNamespace(citation=citation, content="怀化的洪江古商城。")])
    context = AssistantAgentContext(user_id="u", settings=object())

    rendered = _format_rag_contexts(result, context)

    assert rendered.startswith("[1] 怀化的洪江古商城。")
    assert context.citations == [{
        "document_id": "doc-1", "chunk_id": "chunk-1", "source_type": "official",
        "source_id": "source-1", "city_code": "CS", "content": "怀化的洪江古商城。",
    }]


def test_agent_rag_tool_reports_empty_sources_without_citations() -> None:
    from types import SimpleNamespace

    from app.modules.ai_memory.agent import AssistantAgentContext, _format_rag_contexts
    from app.modules.ai_rag.types import RagStatus

    result = SimpleNamespace(status=RagStatus.NO_RESULTS, contexts=(), message="no reviewed content")
    context = AssistantAgentContext(user_id="u", settings=object())

    rendered = _format_rag_contexts(result, context)

    assert rendered == "no reviewed content"
    assert context.citations == []


def test_amap_weather_text_uses_amap_web_service(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from app.modules.ai_memory import agent as agent_module
    from app.modules.maps.service import AMapService

    async def fake_current(self: AMapService, city: str) -> str:
        assert city == "长沙"
        return "长沙市实况：阴，气温 28℃"

    monkeypatch.setattr(AMapService, "current_weather", fake_current)
    settings = SimpleNamespace(amap_web_service_key="key")

    text = asyncio.run(agent_module._amap_weather_text("长沙", settings))

    assert text == "长沙市实况：阴，气温 28℃"


def test_amap_weather_text_returns_none_without_key_or_on_failure(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from app.modules.ai_memory import agent as agent_module
    from app.modules.maps.service import AMapService

    no_key = asyncio.run(agent_module._amap_weather_text("长沙", SimpleNamespace()))
    assert no_key is None

    async def failing_current(self: AMapService, city: str) -> str | None:
        raise RuntimeError("amap down")

    monkeypatch.setattr(AMapService, "current_weather", failing_current)
    text = asyncio.run(agent_module._amap_weather_text("长沙", SimpleNamespace(amap_web_service_key="key")))
    assert text is None


@pytest.mark.anyio
async def test_assistant_quota_exhaustion_returns_upgrade_facts(monkeypatch) -> None:
    from app.modules.ai_memory import router as ai_router

    class ExhaustedQuotas:
        def __init__(self, _: object) -> None:
            pass

        async def consume(self, _: str, __: str) -> object:
            raise AIEntitlementError(source="free", period_end=datetime(2026, 9, 1, tzinfo=UTC))

    monkeypatch.setattr(ai_router, "AIEntitlementService", ExhaustedQuotas)
    with pytest.raises(HTTPException) as error:
        await ask_assistant(
            "conversation-1",
            AssistantAskRequest(text="Plan a trip", client_message_id="quota-test"),
            AccessClaims("owner-1", "session-1", "consumer", ["consumer"]),
            FakeService(),
            object(),
        )

    assert error.value.status_code == 429
    assert error.value.detail == {
        "code": "AI_QUOTA_EXHAUSTED",
        "message": "The AI quota for this period is exhausted.",
        "details": {
            "remaining": 0,
            "period_end": "2026-09-01T00:00:00+00:00",
            "upgrade_available": True,
        },
    }
