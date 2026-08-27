from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.settings import Settings
from app.modules.ai_memory.postgres import AIMemoryRepository, AsyncpgPoolFactory
from app.modules.ai_memory.agent import (
    agent_context_for,
    build_travel_assistant_agent,
    classify_answer as _classify_from_trace,
    run_assistant_agent,
    stream_assistant_agent,
)
from app.modules.ai_memory.schemas import (
    ConversationCreateRequest, ConversationListResponse, ConversationResponse,
    MemoryCreateRequest, MemoryListResponse, MemoryResponse, MemoryUpdateRequest,
    AssistantAskRequest, AssistantAskResponse, MessageCreateRequest, MessageListResponse, MessageResponse,
)
from app.modules.ai_memory.service import AIMemoryError, AIMemoryService
from app.modules.ai_entitlements.service import AIEntitlementError, AIEntitlementService
from app.modules.auth.dependencies import CurrentConsumer
from app.modules.ai_workflows.workflow import DependencyUnavailable


router = APIRouter(prefix="/ai", tags=["ai-memory"])

_TOOL_PROGRESS_MESSAGES = {
    "search_official_knowledge": "Searching reviewed travel knowledge.",
    "search_community_posts": "Searching community posts.",
    "search_personal_memory": "Reading your travel profile.",
    "web_search": "Searching the live web.",
    "fetch_web_page": "Reading web sources.",
}


async def get_ai_memory_service() -> AsyncIterator[AIMemoryService]:
    factory: AsyncpgPoolFactory | None = None
    try:
        settings = Settings()
        if not settings.ai_enabled or not settings.ai_postgres_dsn:
            raise RuntimeError("AI PostgreSQL is not configured")
        factory = AsyncpgPoolFactory(settings.ai_postgres_dsn)
        repository = AIMemoryRepository(await factory.open())
        await repository.setup_schema()
    except Exception as error:
        raise HTTPException(503, detail={"code": "AI_UNAVAILABLE", "message": "AI conversation storage is unavailable."}) from error
    try:
        yield AIMemoryService(repository)
    finally:
        if factory is not None:
            await factory.close()


Service = Annotated[AIMemoryService, Depends(get_ai_memory_service)]
Session = Annotated[AsyncSession, Depends(get_session)]


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(404, detail={"code": code, "message": message})


def _quota_error(error: AIEntitlementError) -> HTTPException:
    return HTTPException(error.status_code, detail={
        "code": error.code,
        "message": error.message,
        "details": {
            "remaining": 0,
            "period_end": error.period_end.isoformat(),
            "upgrade_available": error.upgrade_available,
        },
    })


def _response(model: type[ConversationResponse] | type[MessageResponse] | type[MemoryResponse], row: object):
    values = dict(row)
    if values.get("id") is not None:
        values["id"] = str(values["id"])
    if isinstance(values.get("content"), str):
        import json
        values["content"] = json.loads(values["content"])
    if isinstance(values.get("memory_value"), str):
        import json
        values["memory_value"] = json.loads(values["memory_value"])
    return model.model_validate(values)


def _sse(event: str, event_id: str, data: dict[str, object]) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"


def _citation_fallback_answer(citations: list[dict[str, object]]) -> str:
    """Return a source-grounded answer when the agent stream is unavailable."""
    excerpts = [str(citation.get("content", "")).strip() for citation in citations if citation.get("content")]
    if not excerpts:
        return "暂未找到可用于回答的旅行来源。"
    return "根据已检索到的来源，可参考以下信息：\n\n" + "\n\n".join(excerpts[:3])


def _run_message(run: object) -> dict[str, object]:
    values = dict(run)
    content = values.get("assistant_content")
    if isinstance(content, str):
        content = json.loads(content)
    created_at = values.get("assistant_created_at")
    return {
        "id": str(values.get("assistant_id") or values.get("assistant_message_id")),
        "role": values.get("assistant_role") or "assistant",
        "content": content or {},
        "client_message_id": values.get("assistant_client_message_id"),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
    }


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(claims: CurrentConsumer, service: Service) -> ConversationListResponse:
    return ConversationListResponse(items=[_response(ConversationResponse, row) for row in await service.list_conversations(claims.user_id)])


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(body: ConversationCreateRequest, claims: CurrentConsumer, service: Service) -> ConversationResponse:
    return _response(ConversationResponse, await service.create_conversation(claims.user_id, body.title))


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, claims: CurrentConsumer, service: Service) -> None:
    if not await service.delete_conversation(claims.user_id, conversation_id):
        raise _not_found("AI_CONVERSATION_NOT_FOUND", "The AI conversation is unavailable.")


@router.get("/conversations/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(conversation_id: str, claims: CurrentConsumer, service: Service) -> MessageListResponse:
    messages = await service.list_messages(claims.user_id, conversation_id)
    if messages is None:
        raise _not_found("AI_CONVERSATION_NOT_FOUND", "The AI conversation is unavailable.")
    return MessageListResponse(items=[_response(MessageResponse, row) for row in messages])


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(conversation_id: str, body: MessageCreateRequest, claims: CurrentConsumer, service: Service) -> MessageResponse:
    try:
        message = await service.create_message(claims.user_id, conversation_id, body.role, body.content, body.client_message_id)
    except AIMemoryError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error
    return _response(MessageResponse, message)


@router.post("/conversations/{conversation_id}:ask", response_model=AssistantAskResponse, status_code=status.HTTP_201_CREATED)
async def ask_assistant(conversation_id: str, body: AssistantAskRequest, claims: CurrentConsumer, service: Service, session: Session) -> AssistantAskResponse:
    assistant_client_message_id = f"{body.client_message_id}:assistant"
    existing = await service.get_message_by_client_message_id(claims.user_id, conversation_id, assistant_client_message_id)
    if existing is not None:
        user = await service.get_message_by_client_message_id(claims.user_id, conversation_id, body.client_message_id)
        if user is None:
            raise HTTPException(409, detail={"code": "AI_MESSAGE_STATE_INVALID", "message": "The conversation message state is invalid."})
        return AssistantAskResponse(user_message=_response(MessageResponse, user), assistant_message=_response(MessageResponse, existing))
    if not await service.conversation_exists(claims.user_id, conversation_id):
        raise _not_found("AI_CONVERSATION_NOT_FOUND", "The AI conversation is unavailable.")
    entitlement = None
    try:
        entitlement_service = AIEntitlementService(session)
        entitlement = await entitlement_service.consume(claims.user_id, "assistant_message")
        await session.commit()
        user_message = await service.create_message(
            claims.user_id, conversation_id, "user", {"text": body.text}, body.client_message_id
        )
        settings = Settings()
        agent = build_travel_assistant_agent(settings)
        context = agent_context_for(claims.user_id, settings)
        try:
            text, citations, kind = await run_assistant_agent(agent, body.text, context)
        except DependencyUnavailable:
            if context.citations:
                text, citations, kind = _citation_fallback_answer(context.citations), context.citations, "source_backed"
            else:
                raise
        assistant_content = {"text": text, "citations": citations, "kind": kind}
        assistant_message = await service.create_message(
            claims.user_id, conversation_id, "assistant", assistant_content, assistant_client_message_id
        )
    except AIEntitlementError as error:
        raise _quota_error(error) from error
    except DependencyUnavailable as error:
        if entitlement is not None:
            await entitlement_service.release(entitlement)
            await session.commit()
        raise HTTPException(503, detail={"code": "AI_UNAVAILABLE", "message": str(error)}) from error
    except AIMemoryError as error:
        if entitlement is not None:
            await entitlement_service.release(entitlement)
            await session.commit()
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error
    except Exception as error:
        if entitlement is not None:
            await entitlement_service.release(entitlement)
            await session.commit()
        raise HTTPException(
            503,
            detail={"code": "AI_ASSISTANT_PROCESSING_FAILED", "message": "Assistant processing failed."},
        ) from error
    return AssistantAskResponse(
        user_message=_response(MessageResponse, user_message),
        assistant_message=_response(MessageResponse, assistant_message),
    )


@router.post("/conversations/{conversation_id}:ask-stream", status_code=status.HTTP_201_CREATED)
async def ask_assistant_stream(
    conversation_id: str, body: AssistantAskRequest, claims: CurrentConsumer, service: Service, session: Session
) -> StreamingResponse:
    entitlement = None
    entitlement_service = AIEntitlementService(session)
    try:
        existing = await service.get_message_by_client_message_id(
            claims.user_id, conversation_id, body.client_message_id
        )
        if existing is None:
            if not await service.conversation_exists(claims.user_id, conversation_id):
                raise _not_found("AI_CONVERSATION_NOT_FOUND", "The AI conversation is unavailable.")
            entitlement = await entitlement_service.consume(claims.user_id, "assistant_message")
            await session.commit()
        run = await service.create_assistant_run(claims.user_id, conversation_id, body.client_message_id, body.text)
    except AIEntitlementError as error:
        raise _quota_error(error) from error
    except AIMemoryError as error:
        if entitlement is not None:
            await entitlement_service.release(entitlement)
            await session.commit()
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error

    run_id = str(run["id"])

    async def events() -> AsyncIterator[str]:
        if run["status"] == "completed":
            yield _sse("completed", "completed", {"run_id": run_id, "message": _run_message(run)})
            return
        if run["status"] == "failed":
            yield _sse("failed", "failed", {"run_id": run_id, "code": run.get("error_code"), "message": run.get("error_message")})
            return
        if await service.start_assistant_run(claims.user_id, run_id) is None:
            yield _sse("progress", "running", {"run_id": run_id, "phase": "processing", "message": "Answer generation is in progress."})
            return
        try:
            settings = Settings()
            agent = build_travel_assistant_agent(settings)
            context = agent_context_for(claims.user_id, settings)
            parts: list[str] = []
            citations: list[dict[str, object]] = []
            kind = "general"
            try:
                async for event, payload in stream_assistant_agent(agent, body.text, context):
                    if event == "progress":
                        yield _sse("progress", f"tool-{payload}", {
                            "run_id": run_id,
                            "phase": f"tool:{payload}",
                            "message": _TOOL_PROGRESS_MESSAGES.get(payload, "Gathering information."),
                        })
                    else:
                        parts.append(payload)
                        yield _sse("delta", f"delta-{len(parts)}", {"run_id": run_id, "text": payload})
                text = "".join(parts)
                citations = context.citations
                kind = _classify_from_trace(context)
            except DependencyUnavailable:
                citations = context.citations
                if not citations:
                    raise
                text = _citation_fallback_answer(citations)
                kind = "source_backed"
                yield _sse("delta", "fallback", {"run_id": run_id, "text": text})
            source_mode = "live_web" if kind == "live_web" else "official"
            message = await service.complete_assistant_run(
                claims.user_id, run_id, source_mode,
                {"text": text, "citations": citations, "kind": kind}, f"{body.client_message_id}:assistant",
            )
            if message is None:
                raise RuntimeError("Assistant result could not be persisted.")
            yield _sse("completed", "completed", {"run_id": run_id, "message": _response(MessageResponse, message).model_dump(mode="json")})
        except Exception as error:
            if entitlement is not None:
                await entitlement_service.release(entitlement)
                await session.commit()
            await service.fail_assistant_run(claims.user_id, run_id, "AI_ASSISTANT_PROCESSING_FAILED", "Assistant processing failed.")
            yield _sse("failed", "failed", {"run_id": run_id, "code": "AI_ASSISTANT_PROCESSING_FAILED", "message": "Assistant processing failed."})

    return StreamingResponse(events(), status_code=status.HTTP_201_CREATED, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/assistant-runs/{run_id}/events")
async def replay_assistant_run(run_id: str, claims: CurrentConsumer, service: Service) -> StreamingResponse:
    run = await service.get_assistant_run(claims.user_id, run_id)
    if run is None:
        raise _not_found("AI_ASSISTANT_RUN_NOT_FOUND", "The assistant run is unavailable.")

    async def events() -> AsyncIterator[str]:
        if run["status"] == "completed":
            yield _sse("completed", "completed", {"run_id": run_id, "message": _run_message(run)})
        elif run["status"] == "failed":
            yield _sse("failed", "failed", {"run_id": run_id, "code": run.get("error_code"), "message": run.get("error_message")})
        else:
            yield _sse("progress", "running", {"run_id": run_id, "phase": "processing", "message": "Answer generation is in progress."})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/memories", response_model=MemoryListResponse)
async def list_memories(claims: CurrentConsumer, service: Service) -> MemoryListResponse:
    return MemoryListResponse(items=[_response(MemoryResponse, row) for row in await service.list_memories(claims.user_id)])


@router.post("/memories", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(body: MemoryCreateRequest, claims: CurrentConsumer, service: Service) -> MemoryResponse:
    memory = await service.create_memory(
        claims.user_id,
        body.memory_type,
        body.memory_key,
        body.memory_value,
        body.source,
        body.confidence,
    )
    return _response(MemoryResponse, memory)


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def update_memory(memory_id: str, body: MemoryUpdateRequest, claims: CurrentConsumer, service: Service) -> MemoryResponse:
    memory = await service.update_memory(claims.user_id, memory_id, body.memory_value, body.source, body.confidence)
    if memory is None:
        raise _not_found("AI_MEMORY_NOT_FOUND", "The AI memory is unavailable.")
    return _response(MemoryResponse, memory)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: str, claims: CurrentConsumer, service: Service) -> None:
    if not await service.delete_memory(claims.user_id, memory_id):
        raise _not_found("AI_MEMORY_NOT_FOUND", "The AI memory is unavailable.")
