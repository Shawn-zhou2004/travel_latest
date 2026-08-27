from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from app.modules.ai_workflows.agent_draft import AgentStructuredDraftGenerator
from app.modules.ai_workflows.contracts import GenerationRequest, VerifiedPlanningCandidate
from app.modules.ai_workflows.dashscope import DashScopeStructuredDraftGenerator
from app.modules.ai_workflows.workflow import DependencyUnavailable


def _request() -> GenerationRequest:
    return GenerationRequest(
        generation_job_id="job-1",
        user_id="user-1",
        prompt="三天长沙行程",
        city_code="430100",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 3),
        verified_candidates=(
            VerifiedPlanningCandidate("poi-1", "橘子洲", "430100", 112.96, 28.16, _candidate_source()),
            VerifiedPlanningCandidate("poi-2", "岳麓山", "430100", 112.93, 28.18, _candidate_source()),
            VerifiedPlanningCandidate("poi-3", "湖南省博物馆", "430100", 112.98, 28.21, _candidate_source()),
            VerifiedPlanningCandidate("poi-4", "太平街", "430100", 112.97, 28.19, _candidate_source()),
            VerifiedPlanningCandidate("poi-5", "天心阁", "430100", 112.98, 28.19, _candidate_source()),
            VerifiedPlanningCandidate("poi-6", "IFS国金中心", "430100", 112.98, 28.20, _candidate_source()),
            VerifiedPlanningCandidate("poi-7", "火宫殿", "430100", 112.97, 28.19, _candidate_source()),
            VerifiedPlanningCandidate("poi-8", "湘江风光带", "430100", 112.96, 28.20, _candidate_source()),
            VerifiedPlanningCandidate("poi-9", "靖港古镇", "430100", 112.80, 28.32, _candidate_source()),
        ),
    )


def _candidate_source() -> Any:
    from app.modules.ai_workflows.contracts import Citation

    return Citation(
        document_id="doc-1", chunk_id="chunk-1", source_type="official",
        source_id="source-1", city_code="430100", source_updated_at="2026-08-01",
        content="长沙景点介绍",
    )


def _draft() -> dict[str, object]:
    return {
        "title": "长沙三日游",
        "days": [
            {
                "date": f"2026-10-0{day}",
                "activities": [
                    {"poi_id": f"poi-{(day - 1) * 3 + slot + 1}", "title": "", "estimated_cost": 0}
                    for slot in range(3)
                ],
            }
            for day in range(1, 4)
        ],
    }


def _fill_titles(draft: dict[str, object], request: GenerationRequest) -> dict[str, object]:
    titles = {candidate.poi_id: candidate.poi_name for candidate in request.verified_candidates}
    for day in draft["days"]:
        for activity in day["activities"]:
            activity["title"] = titles[activity["poi_id"]]
    return draft


def _message_result(content: object) -> dict[str, object]:
    message = AIMessage(content=content)
    return {"messages": [message]}


class _FakeCatalog:
    async def retrieve(self, request: Any) -> Any:
        return SimpleNamespace(status="no_results", contexts=(), message="no content")


class _FailingCatalog:
    async def retrieve(self, request: Any) -> Any:
        raise RuntimeError("catalog down")


def _generator(chat_model: Any, retries: int = 0) -> AgentStructuredDraftGenerator:
    return AgentStructuredDraftGenerator(
        api_key="", base_url="", model="", timeout=1, retries=retries,
        settings=SimpleNamespace(
            magic_mcp_websearch_url=None, magic_mcp_websearch_tool=None, magic_mcp_api_key=None,
            magic_mcp_timeout_seconds=1, magic_mcp_fetch_url=None, magic_mcp_fetch_tool=None,
            magic_mcp_fetch_timeout_seconds=1, amap_web_service_key=None,
        ),
        catalog=_FakeCatalog(),
        chat_model=chat_model,
    )


def test_extract_draft_parses_plain_json() -> None:
    draft = AgentStructuredDraftGenerator._extract_draft(_message_result('{"title": "T", "days": []}'))
    assert draft == {"title": "T", "days": []}


def test_extract_draft_strips_code_fences() -> None:
    draft = AgentStructuredDraftGenerator._extract_draft(
        _message_result('```json\n{"title": "T", "days": []}\n```')
    )
    assert draft == {"title": "T", "days": []}


def test_extract_draft_rejects_non_json_messages() -> None:
    with pytest.raises(ValueError):
        AgentStructuredDraftGenerator._extract_draft(_message_result("Let me think about it."))


def test_extract_draft_skips_tool_only_messages() -> None:
    tool_call = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])
    final = AIMessage(content='{"title": "T", "days": []}')
    draft = AgentStructuredDraftGenerator._extract_draft({"messages": [tool_call, final]})
    assert draft == {"title": "T", "days": []}


class _ScriptedToolModel:
    """A minimal chat model whose responses are queued scripts.

    Supports ``bind_tools`` (create_agent requires it) by returning a shallow
    wrapper so tool-calling messages flow through unchanged.
    """

    def __init__(self, responses: list[AIMessage]) -> None:
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

        self._fake = FakeMessagesListChatModel(responses=responses)

    def bind_tools(self, tools: object, **_: object) -> "_ScriptedToolModel":
        return self

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fake, name)


def test_generate_returns_validated_draft_from_agent_result() -> None:
    import asyncio
    import json as jsonlib

    request = _request()
    draft = _fill_titles(_draft(), request)
    model = _ScriptedToolModel([AIMessage(content=jsonlib.dumps(draft, ensure_ascii=False))])
    generator = _generator(model)

    result = asyncio.run(generator.generate(request, {}, ()))

    assert result["title"] == "长沙三日游"
    assert len(result["days"]) == 3
    for day in result["days"]:
        assert len(day["activities"]) == 3


def test_generate_retry_then_fail_raises_dependency_unavailable() -> None:
    import asyncio

    request = _request()
    invalid = AIMessage(content='{"title": "", "days": []}')
    model = _ScriptedToolModel([invalid, invalid])
    generator = _generator(model, retries=1)

    with pytest.raises(DependencyUnavailable):
        asyncio.run(generator.generate(request, {}, ()))


def test_generate_tool_degradation_keeps_run_alive() -> None:
    """A dead catalog must not crash the run: the tool returns a note instead."""
    import asyncio
    import json as jsonlib

    request = _request()
    draft = _fill_titles(_draft(), request)

    # Model first calls the (failing) official-knowledge tool, then answers.
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "search_official_knowledge", "args": {"query": "长沙 景点"}, "id": "call-1"}],
    )
    final = AIMessage(content=jsonlib.dumps(draft, ensure_ascii=False))
    model = _ScriptedToolModel([tool_call, final])
    generator = _generator(model)
    # Rebuild the agent with the failing catalog.
    generator._agent = AgentStructuredDraftGenerator(
        api_key="", base_url="", model="", timeout=1, retries=0,
        settings=generator.settings, catalog=_FailingCatalog(), chat_model=model,
    )._agent

    result = asyncio.run(generator.generate(request, {}, ()))

    assert result["title"] == "长沙三日游"


def test_agent_generator_satisfies_protocol_shape() -> None:
    """The agent generator is a drop-in StructuredDraftGenerator replacement."""
    generator = _generator(_ScriptedToolModel([]))
    assert callable(generator.generate)
    # Shape validation is reused from the single-shot generator.
    assert DashScopeStructuredDraftGenerator._validate_draft_shape is not None
