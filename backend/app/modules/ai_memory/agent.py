"""Tool-calling agent for the consumer travel assistant.

Replaces the previous rule-based intent router (regex intent -> fixed retrieval
chain) with a LangGraph/LangChain ``create_agent`` ReAct loop: the model decides
which knowledge source to query, in which order, and how many rounds it needs.

Design rules:
- Citations keep the exact dict shape the persistence layer already stores, so
  ``ai_messages.content`` and the SSE payloads stay wire-compatible.
- ``user_id`` is injected through ``ToolRuntime.context`` and never exposed as a
  tool argument the model could forge.
- Every tool degrades gracefully: an unavailable dependency returns a textual
  "source unavailable" note so the agent can fall back to other tools instead
  of failing the whole run.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.runtime import Runtime

from app.core.settings import Settings
from app.modules.ai_rag.catalog import DomainRetrievalRequest
from app.modules.ai_rag.types import KnowledgeDomain, RagStatus
from app.modules.ai_workflows.runtime import open_domain_retrieval_runtime
from app.modules.ai_workflows.workflow import DependencyUnavailable

# Cap the ReAct loop so a runaway model cannot burn unbounded tokens.
ASSISTANT_RECURSION_LIMIT = 12
# How many RAG contexts each retrieval tool reports back to the model.
_MAX_TOOL_CONTEXTS = 6

_SYSTEM_PROMPT = """You are the in-app travel planning assistant of an AI travel platform.

Answer the user's question by choosing tools yourself:
- Official reviewed knowledge (`search_official_knowledge`) is the default for
  destinations, attractions, routes, and travel facts. Try it first.
- Community posts (`search_community_posts`) help with subjective experience:
  real trips, crowd levels, food recommendations, warnings.
- The user's personal memory (`search_personal_memory`) holds their own travel
  profile, past trips, and preferences. Use it when the answer depends on who
  the user is or what they previously told the platform.
- `get_weather` and `get_weather_forecast` answer current weather and the next
  few days' forecast for a city. Prefer them over web search for weather.
- For other time-sensitive facts (opening hours, current prices,
  ticket availability) or anything the knowledge tools cannot answer, use
  `web_search`, and `fetch_web_page` on the most promising result URLs.
- For greetings or small talk that needs no facts, just reply directly.

Rules:
- Ground every factual claim in tool results. Never invent attractions,
  prices, hours, or routes.
- Cite sources inline with bracketed numbers like [1][2] in the order you
  retrieved them.
- If no source answers the question, say so plainly and ask for one concrete
  clarification (e.g. destination city).
- Reply in the user's language, concise plain text, no markdown headings.
"""


@dataclass
class AssistantAgentContext:
    """Per-run context injected into every tool via ToolRuntime."""

    user_id: str
    settings: Settings
    # Citation accumulator shared with the caller; tools append here so the
    # persistence layer can store the same citations shape as before.
    citations: list[dict[str, object]] = field(default_factory=list)
    tool_trace: list[str] = field(default_factory=list)


def _format_rag_contexts(result: Any, context: AssistantAgentContext) -> str:
    """Render RAG contexts for the model and collect citation dicts."""
    if result.status != RagStatus.AVAILABLE or not result.contexts:
        return result.message or "No matching content in this knowledge source."
    lines: list[str] = []
    for item in result.contexts[:_MAX_TOOL_CONTEXTS]:
        citation = {
            "document_id": item.citation.document_id,
            "chunk_id": item.citation.chunk_id,
            "source_type": item.citation.source_type.value,
            "source_id": item.citation.source_id,
            "city_code": item.citation.city_code,
            "content": item.content,
        }
        context.citations.append(citation)
        index = len(context.citations)
        lines.append(f"[{index}] {item.content}")
    return "\n\n".join(lines)


async def _amap_weather_text(city: str, settings: Any, *, days: int | None = None) -> str | None:
    """Weather source: the AMap web service. Returns None when unusable."""
    api_key = getattr(settings, "amap_web_service_key", None)
    if not api_key:
        return None
    from app.modules.maps.service import AMapService

    service = AMapService(api_key=api_key)
    try:
        if days is None:
            return await service.current_weather(city)
        return await service.weather_forecast(city, days=days)
    except Exception:  # noqa: BLE001
        return None


def _build_tools() -> list[Any]:
    """Create the five assistant tools bound to AssistantAgentContext."""

    @tool
    async def search_official_knowledge(query: str, runtime: ToolRuntime[AssistantAgentContext]) -> str:
        """Search the platform's officially reviewed travel knowledge base.

        Use for destinations, attractions, routes, policies, and travel facts.
        Input should be a concise Chinese or English search query.
        """
        context = runtime.context
        catalog = context.settings
        try:
            domain_runtime = await open_domain_retrieval_runtime(catalog)
            try:
                result = await domain_runtime.catalog.retrieve(
                    DomainRetrievalRequest(KnowledgeDomain.OFFICIAL, query, city_code=None)
                )
            finally:
                await domain_runtime.close()
        except (DependencyUnavailable, Exception) as error:  # noqa: BLE001 - degrade, don't fail the run
            return f"Official knowledge source is temporarily unavailable ({type(error).__name__}). Try other tools or answer from what you already have."
        context.tool_trace.append("official_rag")
        return _format_rag_contexts(result, context)

    @tool
    async def search_community_posts(query: str, runtime: ToolRuntime[AssistantAgentContext]) -> str:
        """Search community-written travel posts and field notes.

        Use for subjective experience: real trip reports, crowd tips, food
        recommendations, and warnings from other travelers.
        """
        context = runtime.context
        try:
            domain_runtime = await open_domain_retrieval_runtime(context.settings)
            try:
                result = await domain_runtime.catalog.retrieve(
                    DomainRetrievalRequest(KnowledgeDomain.COMMUNITY, query, city_code=None)
                )
            finally:
                await domain_runtime.close()
        except (DependencyUnavailable, Exception) as error:  # noqa: BLE001
            return f"Community knowledge source is temporarily unavailable ({type(error).__name__}). Try other tools."
        context.tool_trace.append("community_rag")
        return _format_rag_contexts(result, context)

    @tool
    async def search_personal_memory(query: str, runtime: ToolRuntime[AssistantAgentContext]) -> str:
        """Search the current user's private travel profile, memories, and past trips.

        Use when the answer depends on this specific user's preferences,
        constraints, or history. Access is restricted to the current user.
        """
        context = runtime.context
        try:
            domain_runtime = await open_domain_retrieval_runtime(context.settings)
            try:
                result = await domain_runtime.catalog.retrieve(
                    DomainRetrievalRequest(
                        KnowledgeDomain.USER_MEMORY, query, city_code=None, user_id=context.user_id
                    )
                )
            finally:
                await domain_runtime.close()
        except (DependencyUnavailable, Exception) as error:  # noqa: BLE001
            return f"Personal memory is temporarily unavailable ({type(error).__name__}). Answer without personal context."
        context.tool_trace.append("personal_rag")
        return _format_rag_contexts(result, context)

    @tool
    async def get_weather(city: str, runtime: ToolRuntime[AssistantAgentContext]) -> str:
        """Get the current weather for a city.

        Use when the user asks about today's or right-now weather: temperature,
        conditions, wind, humidity. Input is a city name in Chinese or English,
        or a 6-digit adcode.
        """
        context = runtime.context
        settings = context.settings
        text = await _amap_weather_text(city, settings)
        if text is None:
            return "Weather service is not configured on this deployment."
        context.tool_trace.append("weather")
        context.citations.append({
            "document_id": f"live-weather:{city}",
            "chunk_id": f"live-weather:{city}",
            "source_type": "live_weather",
            "source_id": "weather_service",
            "city_code": "",
            "content": text,
        })
        return f"[{len(context.citations)}] {text}"

    @tool
    async def get_weather_forecast(city: str, days: int, runtime: ToolRuntime[AssistantAgentContext]) -> str:
        """Get the weather forecast for a city for the next few days.

        Use when the user asks about weather on upcoming travel dates, up to
        4 days ahead. Input is a city name (or 6-digit adcode) and the number
        of days.
        """
        context = runtime.context
        settings = context.settings
        text = await _amap_weather_text(city, settings, days=days)
        if text is None:
            return "Weather forecast service is not configured on this deployment."
        context.tool_trace.append("weather")
        context.citations.append({
            "document_id": f"live-weather:{city}",
            "chunk_id": f"live-weather:{city}:forecast",
            "source_type": "live_weather",
            "source_id": "weather_service",
            "city_code": "",
            "content": text,
        })
        return f"[{len(context.citations)}] {text}"

    @tool
    async def web_search(query: str, runtime: ToolRuntime[AssistantAgentContext]) -> str:
        """Search the live web for current information.

        Use for time-sensitive facts such as today's weather, current prices,
        opening hours, ticket availability, or anything the knowledge tools
        could not answer.
        """
        from app.integrations.mcp.websearch import (
            MagicMcpWebSearchProvider,
            UnavailableWebSearchProvider,
            rank_web_search_candidates,
        )
        import httpx

        context = runtime.context
        settings = context.settings
        if not (settings.magic_mcp_websearch_url and settings.magic_mcp_websearch_tool and settings.magic_mcp_api_key):
            return "Web search is not configured on this deployment."
        try:
            async with httpx.AsyncClient(timeout=settings.magic_mcp_timeout_seconds) as client:
                provider = MagicMcpWebSearchProvider(
                    endpoint=settings.magic_mcp_websearch_url,
                    tool=settings.magic_mcp_websearch_tool,
                    api_key=settings.magic_mcp_api_key,
                    timeout=settings.magic_mcp_timeout_seconds,
                    client=client,
                )
                candidates = await provider.search(query, limit=8)
        except Exception as error:  # noqa: BLE001
            return f"Web search is temporarily unavailable ({type(error).__name__})."
        candidates = rank_web_search_candidates(query, candidates, limit=5)
        if not candidates:
            return "Web search returned no results."
        context.tool_trace.append("web_search")
        lines: list[str] = []
        for candidate in candidates:
            citation = {
                "document_id": f"live-web:{candidate.source_url}",
                "chunk_id": f"live-web:{candidate.source_url}",
                "source_type": "live_web",
                "source_id": candidate.source_url,
                "source_host": candidate.source_host,
                "city_code": "",
                "content": f"{candidate.title}\n{candidate.excerpt}",
            }
            context.citations.append(citation)
            index = len(context.citations)
            lines.append(f"[{index}] {candidate.title}\n{candidate.excerpt}\nURL: {candidate.source_url}")
        return "\n\n".join(lines)

    @tool
    async def fetch_web_page(url: str, runtime: ToolRuntime[AssistantAgentContext]) -> str:
        """Fetch and read the full text of a web page URL.

        Use after web_search when a result looks promising but the excerpt is
        not detailed enough. Input must be a complete http(s) URL.
        """
        from app.integrations.mcp.websearch import chunk_web_content
        import httpx

        context = runtime.context
        settings = context.settings
        if not (settings.magic_mcp_fetch_url and settings.magic_mcp_fetch_tool and settings.magic_mcp_api_key):
            return "Web page fetching is not configured on this deployment."
        try:
            async with httpx.AsyncClient(timeout=settings.magic_mcp_fetch_timeout_seconds) as client:
                from app.integrations.mcp.websearch import MagicMcpWebPageFetcher

                fetcher = MagicMcpWebPageFetcher(
                    endpoint=settings.magic_mcp_fetch_url,
                    tool=settings.magic_mcp_fetch_tool,
                    api_key=settings.magic_mcp_api_key,
                    timeout=settings.magic_mcp_fetch_timeout_seconds,
                    client=client,
                )
                page_text = await fetcher.fetch(url)
        except Exception as error:  # noqa: BLE001
            return f"Could not fetch this page ({type(error).__name__}). Try another URL."
        if not page_text:
            return "The page returned empty content."
        context.tool_trace.append("fetch_web_page")
        chunks = chunk_web_content(page_text)[:3]
        lines: list[str] = []
        for chunk in chunks:
            citation = {
                "document_id": f"live-web:{url}",
                "chunk_id": f"live-web:{url}:{len(context.citations)}",
                "source_type": "live_web",
                "source_id": url,
                "city_code": "",
                "content": chunk,
            }
            context.citations.append(citation)
            index = len(context.citations)
            lines.append(f"[{index}] {chunk}")
        return "\n\n".join(lines)

    return [
        search_official_knowledge,
        search_community_posts,
        search_personal_memory,
        get_weather,
        get_weather_forecast,
        web_search,
        fetch_web_page,
    ]


def build_travel_assistant_agent(settings: Settings) -> Any:
    """Create the ReAct assistant agent on the LangGraph runtime.

    The model talks to the DashScope OpenAI-compatible endpoint through
    ChatOpenAI, so no extra vendor SDK is needed.
    """
    model = ChatOpenAI(
        model=settings.llm_model or "qwen-plus",
        api_key=settings.dashscope_api_key or "",
        base_url=settings.llm_base_url or None,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )
    return create_agent(
        model,
        _build_tools(),
        system_prompt=_SYSTEM_PROMPT,
        context_schema=AssistantAgentContext,
    )


def _final_text(result: dict[str, Any]) -> str:
    messages = result.get("messages", [])
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if getattr(message, "type", "") == "ai" and isinstance(content, str) and content.strip():
            return content.strip()
        # Standard content-blocks form.
        if getattr(message, "type", "") == "ai" and isinstance(content, list):
            text = "".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
            if text.strip():
                return text.strip()
    return ""


def classify_answer(context: AssistantAgentContext) -> str:
    """Map tool usage back onto the persisted ``kind`` field."""
    trace = set(context.tool_trace)
    if "web_search" in trace or "fetch_web_page" in trace or "weather" in trace:
        return "live_web"
    if trace:
        return "source_backed"
    return "general"


async def run_assistant_agent(
    agent: Any, question: str, context: AssistantAgentContext
) -> tuple[str, list[dict[str, object]], str]:
    """Run the agent loop and return ``(answer_text, citations, kind)``."""
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        context=context,
        config={"recursion_limit": ASSISTANT_RECURSION_LIMIT},
    )
    text = _final_text(result)
    if not text:
        raise DependencyUnavailable("dashscope", "Assistant agent returned an empty answer.")
    return text, context.citations, classify_answer(context)


async def stream_assistant_agent(
    agent: Any, question: str, context: AssistantAgentContext
) -> AsyncIterator[tuple[str, str]]:
    """Stream the agent loop.

    Yields ``("delta", text)`` chunks for model tokens and
    ``("progress", tool_name)`` notifications when a tool starts, so the SSE
    layer can surface retrieval phases to the UI.
    """
    seen_tools: set[str] = set()
    emitted = False
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": question}]},
        context=context,
        version="v2",
        config={"recursion_limit": ASSISTANT_RECURSION_LIMIT},
    ):
        kind = event["event"]
        if kind == "on_tool_start":
            tool_name = str(event.get("name", ""))
            if tool_name and tool_name not in seen_tools:
                seen_tools.add(tool_name)
                yield "progress", tool_name
        elif kind == "on_chat_model_stream":
            message = event["data"].get("chunk")
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                emitted = True
                yield "delta", content
            elif isinstance(content, list):
                text = "".join(
                    block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
                )
                if text:
                    emitted = True
                    yield "delta", text
    if not emitted:
        raise DependencyUnavailable("dashscope", "Assistant agent returned an empty answer.")


def agent_context_for(user_id: str, settings: Settings) -> AssistantAgentContext:
    return AssistantAgentContext(user_id=user_id, settings=settings)
