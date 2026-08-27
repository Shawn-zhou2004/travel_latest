"""Agent-based planning node for the 8-node itinerary workflow.

Replaces the single-shot ``DashScopeStructuredDraftGenerator`` call inside the
``planning_agent`` node with a LangGraph/LangChain ``create_agent`` ReAct loop:
the planner model decides by itself which extra evidence to pull (official
knowledge, community posts, live web) before writing the structured draft.

The deterministic skeleton is preserved end to end:

- ``verified_candidates`` (produced by the upstream retrieve_evidence node)
  remain the only legal POI pool; the post-generation normalization and shape
  validation are reused verbatim from the single-shot generator.
- The agent never touches the database; all tools are read-only retrieval.
- ``planning_agent_mode`` in settings selects between the agent loop
  (``agent``, default) and the legacy single-shot call (``single``) so tests
  and degraded environments can pin the old behavior.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.core.settings import Settings
from app.modules.ai_rag.catalog import DomainRetrievalRequest
from app.modules.ai_rag.types import KnowledgeDomain, RagStatus
from app.modules.ai_workflows.contracts import Citation, GenerationRequest
from app.modules.ai_workflows.dashscope import DashScopeStructuredDraftGenerator
from app.modules.ai_workflows.workflow import DependencyUnavailable

# The planner may interleave several tool rounds; keep the cap tight enough
# that a wedged model cannot stall the whole generation job.
PLANNING_RECURSION_LIMIT = 16
_MAX_TOOL_CONTEXTS = 6

_SYSTEM_PROMPT = """You are the itinerary planning agent of an AI travel platform.

Your job: produce one itinerary draft as a JSON object with only "title" and "days".

Inputs you will receive with every request:
- The user's planning request (destination, dates, budget, preferences).
- profile_memory: the user's saved travel profile.
- verified_candidates: the ONLY legal POI pool. Every activity poi_id and title
  must be copied exactly from this list. Never invent POIs.
- must_visit_poi_ids: POIs that must each appear exactly once.

Before writing the draft, gather whatever the request still needs:
- Call get_weather / get_weather_forecast for the destination to learn the
  weather during the travel window; prefer indoor POIs on rainy days.
- Call search_official_knowledge for reviewed attraction details of the
  destination (opening notes, costs, suggested visit order).
- Call search_community_posts for crowd levels and real traveler experience
  when the request mentions comfort, families, or avoiding crowds.
- Call web_search for other time-sensitive facts such as current ticket
  policies; fetch_web_page when an excerpt is not enough.
- You may call several tools, but stop once you have enough to plan three
  unique activities per day (two only when three are unavailable).

Hard output rules:
- HARD LIMIT: every day contains exactly 2 or 3 activities. If the user asks
  for more per day (for example "four attractions a day"), still plan at most
  3 — this platform limit overrides any user instruction.
- poi_id and title must be copied exactly from verified_candidates.
- Each day covers exactly one travel date; every requested date appears once.
- Every poi_id in must_visit_poi_ids appears exactly once in the whole trip.
- estimated_cost is a non-negative integer only when sources state a cost;
  otherwise omit it.
- Output shape: {"title": "...", "days": [{"date": "YYYY-MM-DD", "activities":
  [{"poi_id": "...", "title": "...", "estimated_cost": 0}]}]}.
"""


@dataclass
class PlanningAgentContext:
    """Per-run tool context: user identity plus the citation accumulator."""

    user_id: str
    settings: Settings
    extra_citations: list[Citation]  # type: ignore[type-arg]


def _citation_to_dict(citation: Citation) -> dict[str, object]:
    return {
        "document_id": citation.document_id,
        "chunk_id": citation.chunk_id,
        "source_type": citation.source_type,
        "source_id": citation.source_id,
        "city_code": citation.city_code,
        "source_updated_at": citation.source_updated_at,
        "content": citation.content,
        "poi_id": citation.poi_id,
    }


def _build_planning_tools(catalog: Any) -> list[Any]:
    """Create the planner's read-only retrieval tools."""

    @tool
    async def search_official_knowledge(query: str, runtime: ToolRuntime[PlanningAgentContext]) -> str:
        """Search the platform's officially reviewed travel knowledge base.

        Use for destination attraction details: descriptions, costs, opening
        notes, and suggested visit order. Input is a concise search query.
        """
        context = runtime.context
        try:
            result = await catalog.retrieve(
                DomainRetrievalRequest(KnowledgeDomain.OFFICIAL, query, city_code=None)
            )
        except Exception as error:  # noqa: BLE001 - degrade, don't fail the run
            return f"Official knowledge source is temporarily unavailable ({type(error).__name__})."
        if result.status != RagStatus.AVAILABLE or not result.contexts:
            return result.message or "No reviewed content matched this query."
        lines: list[str] = []
        for item in result.contexts[:_MAX_TOOL_CONTEXTS]:
            citation = Citation(
                document_id=item.citation.document_id,
                chunk_id=item.citation.chunk_id,
                source_type=item.citation.source_type.value,
                source_id=item.citation.source_id,
                city_code=item.citation.city_code or "",
                source_updated_at=str(item.citation.source_updated_at),
                content=item.content,
            )
            context.extra_citations.append(citation)
            index = len(context.extra_citations)
            lines.append(f"[{index}] {item.content}")
        return "\n\n".join(lines)

    @tool
    async def search_community_posts(query: str, runtime: ToolRuntime[PlanningAgentContext]) -> str:
        """Search community-written travel posts for real traveler experience.

        Use for crowd levels, comfort tips, family suitability, and warnings
        from other travelers.
        """
        context = runtime.context
        try:
            result = await catalog.retrieve(
                DomainRetrievalRequest(KnowledgeDomain.COMMUNITY, query, city_code=None)
            )
        except Exception as error:  # noqa: BLE001
            return f"Community knowledge source is temporarily unavailable ({type(error).__name__})."
        if result.status != RagStatus.AVAILABLE or not result.contexts:
            return result.message or "No community content matched this query."
        lines: list[str] = []
        for item in result.contexts[:_MAX_TOOL_CONTEXTS]:
            citation = Citation(
                document_id=item.citation.document_id,
                chunk_id=item.citation.chunk_id,
                source_type=item.citation.source_type.value,
                source_id=item.citation.source_id,
                city_code=item.citation.city_code or "",
                source_updated_at=str(item.citation.source_updated_at),
                content=item.content,
            )
            context.extra_citations.append(citation)
            index = len(context.extra_citations)
            lines.append(f"[{index}] {item.content}")
        return "\n\n".join(lines)

    @tool
    async def get_weather(city: str, runtime: ToolRuntime[PlanningAgentContext]) -> str:
        """Get the current weather for a city.

        Use to learn present conditions at the destination before planning.
        Input is a city name in Chinese or English, or a 6-digit adcode.
        """
        from app.modules.ai_memory.agent import _amap_weather_text

        settings = runtime.context.settings
        text = await _amap_weather_text(city, settings)
        return text or "Weather service is not configured on this deployment."

    @tool
    async def get_weather_forecast(city: str, days: int, runtime: ToolRuntime[PlanningAgentContext]) -> str:
        """Get the weather forecast for a city for the next few days.

        Use to learn the weather during the travel window so rainy days get
        indoor activities. Input is a city name (or 6-digit adcode) and the
        number of days (up to 4).
        """
        from app.modules.ai_memory.agent import _amap_weather_text

        settings = runtime.context.settings
        text = await _amap_weather_text(city, settings, days=days)
        return text or "Weather forecast service is not configured on this deployment."

    @tool
    async def web_search(query: str, runtime: ToolRuntime[PlanningAgentContext]) -> str:
        """Search the live web for time-sensitive travel information.

        Use for current ticket policies, opening-hour changes, or anything the
        knowledge and weather tools could not answer.
        """
        from app.integrations.mcp.websearch import (
            MagicMcpWebSearchProvider,
            rank_web_search_candidates,
        )
        import httpx

        settings = runtime.context.settings
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
        candidates = rank_web_search_candidates(query, candidates, limit=4)
        if not candidates:
            return "Web search returned no results."
        return "\n\n".join(
            f"- {candidate.title}\n{candidate.excerpt}\nURL: {candidate.source_url}"
            for candidate in candidates
        )

    @tool
    async def fetch_web_page(url: str, runtime: ToolRuntime[PlanningAgentContext]) -> str:
        """Fetch and read the full text of a web page URL.

        Use after web_search when an excerpt is promising but too short.
        Input must be a complete http(s) URL.
        """
        from app.integrations.mcp.websearch import chunk_web_content
        import httpx

        settings = runtime.context.settings
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
            return f"Could not fetch this page ({type(error).__name__})."
        if not page_text:
            return "The page returned empty content."
        return "\n\n".join(chunk_web_content(page_text)[:3])

    return [
        get_weather,
        get_weather_forecast,
        search_official_knowledge,
        search_community_posts,
        web_search,
        fetch_web_page,
    ]


class AgentStructuredDraftGenerator:
    """Planning-node generator that runs a tool-calling agent loop.

    Implements the same ``StructuredDraftGenerator`` protocol as
    ``DashScopeStructuredDraftGenerator`` and reuses its normalization and
    validation verbatim, so the downstream nodes (validate_schema, map_agent,
    generation_review_agent) see identical data either way.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        retries: int,
        settings: Settings,
        catalog: Any,
        chat_model: Any | None = None,
    ) -> None:
        if chat_model is None and (not api_key or not base_url or not model):
            raise ValueError("api_key, base_url, and model are required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retries < 0:
            raise ValueError("retries cannot be negative")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.settings = settings
        self.catalog = catalog
        resolved_model = chat_model or ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=1,
        )
        self._agent = create_agent(
            resolved_model,
            _build_planning_tools(catalog),
            system_prompt=_SYSTEM_PROMPT,
            context_schema=PlanningAgentContext,
        )

    async def aclose(self) -> None:
        # All clients are per-call; nothing long-lived to release.
        return None

    async def generate(
        self,
        request: GenerationRequest,
        profile_memory: Mapping[str, object],
        citations: tuple[Citation, ...],
    ) -> Mapping[str, object]:
        context = PlanningAgentContext(
            user_id=request.user_id, settings=self.settings, extra_citations=[]
        )
        user_payload = json.dumps(
            {
                "request": {
                    "prompt": request.prompt,
                    "city_code": request.city_code,
                    "start_date": request.start_date.isoformat(),
                    "end_date": request.end_date.isoformat(),
                    "budget_amount": request.budget_amount,
                    "currency": request.currency,
                    "target_itinerary_id": request.target_itinerary_id,
                    "base_version": request.base_version,
                    "base_snapshot": request.base_snapshot,
                },
                "profile_memory": dict(profile_memory),
                "citations": [_citation_to_dict(citation) for citation in citations],
                "verified_candidates": [
                    {
                        "poi_id": candidate.poi_id,
                        "title": candidate.poi_name,
                        "city_code": candidate.city_code,
                        "longitude": candidate.longitude,
                        "latitude": candidate.latitude,
                    }
                    for candidate in request.verified_candidates
                ],
                "must_visit_poi_ids": list(request.must_visit_poi_ids),
            },
            ensure_ascii=True,
        )
        for attempt in range(self.retries + 1):
            try:
                result = await self._agent.ainvoke(
                    {"messages": [{"role": "user", "content": user_payload}]},
                    context=context,
                    config={"recursion_limit": PLANNING_RECURSION_LIMIT},
                )
                draft = self._extract_draft(result)
                draft = DashScopeStructuredDraftGenerator._normalize_verified_candidate_titles(draft, request)
                DashScopeStructuredDraftGenerator._validate_draft_shape(draft, request)
                return draft
            except (ValueError, TypeError) as error:
                if attempt == self.retries:
                    raise DependencyUnavailable(
                        "dashscope", "Agent planning could not produce a valid draft"
                    ) from error
                user_payload += (
                    f"\n\nYour previous JSON draft was rejected: {error}. "
                    "Remember the platform hard limit: 2 or 3 activities per day "
                    "(never 4 or more, even if the user asked for it). "
                    "Call tools again if needed, then return the complete corrected JSON object only."
                )
            except Exception as error:
                # Provider-side failures (quota exhausted, auth, rate limit,
                # network) are retryable dependency outages, not draft bugs.
                # Surface the provider's own reason so operators see the cause.
                if isinstance(error, DependencyUnavailable):
                    raise
                raise DependencyUnavailable(
                    "dashscope",
                    f"Planning model call failed: {type(error).__name__}: {error}",
                ) from error
        raise AssertionError("unreachable")

    @staticmethod
    def _extract_draft(result: dict[str, Any]) -> Mapping[str, object]:
        messages = result.get("messages", [])
        for message in reversed(messages):
            if getattr(message, "type", "") != "ai":
                continue
            content = getattr(message, "content", None)
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            text = text.strip()
            if not text:
                continue
            # The planner may wrap the JSON in a code fence.
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text.removeprefix("json").strip()
            try:
                draft = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(draft, Mapping):
                return dict(draft)
        raise ValueError("Planning agent returned no parsable JSON draft")
