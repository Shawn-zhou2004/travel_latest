from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx
import pytest

from app.modules.ai_workflows.contracts import Citation, GenerationRequest, StructuredDraftGenerator, VerifiedPlanningCandidate
from app.modules.ai_workflows.dashscope import DashScopeStructuredDraftGenerator
from app.modules.ai_workflows.workflow import DependencyUnavailable


def _request() -> GenerationRequest:
    return GenerationRequest("job-1", "user-1", "Plan a museum visit", "010", date(2026, 9, 1), date(2026, 9, 1), 100)


def _citations() -> tuple[Citation, ...]:
    return (Citation("doc-1", "chunk-1", "poi", "source-1", "010", "2026-08-01T00:00:00Z", "Museum poi-1 costs 40 CNY."),)


def test_dashscope_generator_uses_openai_compatible_structured_completion() -> None:
    async def scenario() -> None:
        received: httpx.Request | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal received
            received = request
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"title":"Museum day","days":[{"date":"2026-09-01","activities":[{"poi_id":"poi-1","title":"Museum","estimated_cost":40}]}]}'}}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        generator: StructuredDraftGenerator = DashScopeStructuredDraftGenerator(
            api_key="secret", base_url="https://dashscope.example/compatible-mode/v1/", model="qwen-test", timeout=7, retries=1, client=client
        )
        draft = await generator.generate(_request(), {"pace": "slow"}, _citations())

        assert draft["title"] == "Museum day"
        assert received is not None
        assert received.url == "https://dashscope.example/compatible-mode/v1/chat/completions"
        assert received.headers["Authorization"] == "Bearer secret"
        body = json.loads(received.content)
        assert body["model"] == "qwen-test"
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][1]["content"]
        assert "only" in body["messages"][0]["content"].lower()
        assert "must contain a non-empty poi_id" in body["messages"][0]["content"]
        assert json.loads(body["messages"][1]["content"])["citations"] == [
            {"document_id": "doc-1", "chunk_id": "chunk-1", "source_type": "poi", "source_id": "source-1", "city_code": "010", "source_updated_at": "2026-08-01T00:00:00Z", "content": "Museum poi-1 costs 40 CNY."}
        ]
        await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, json={"choices": []}), httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})])
def test_dashscope_generator_converts_http_and_malformed_responses_to_dependency_unavailable(response: httpx.Response) -> None:
    async def scenario() -> None:
        attempts = 0

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return response

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        generator = DashScopeStructuredDraftGenerator(api_key="secret", base_url="https://dashscope.example/v1", model="qwen-test", timeout=1, retries=1, client=client)
        with pytest.raises(DependencyUnavailable) as error:
            await generator.generate(_request(), {}, _citations())
        assert error.value.dependency == "dashscope"
        assert attempts == 2
        await client.aclose()

    asyncio.run(scenario())


def test_dashscope_generator_converts_network_failures_to_dependency_unavailable() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        generator = DashScopeStructuredDraftGenerator(api_key="secret", base_url="https://dashscope.example/v1", model="qwen-test", timeout=1, retries=0, client=client)
        with pytest.raises(DependencyUnavailable) as error:
            await generator.generate(_request(), {}, _citations())
        assert error.value.dependency == "dashscope"
        await client.aclose()

    asyncio.run(scenario())


def test_dashscope_generator_retries_a_json_draft_missing_required_activity_fields() -> None:
    async def scenario() -> None:
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(200, json={"choices": [{"message": {"content": '{"title":"Museum day","days":[{"date":"2026-09-01","activities":[{"title":"Museum"}]}]}'}}]})
            body = json.loads(request.content)
            assert "previous JSON draft was invalid" in body["messages"][-1]["content"]
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"title":"Museum day","days":[{"date":"2026-09-01","activities":[{"poi_id":"poi-1","title":"Museum"}]}]}'}}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        generator = DashScopeStructuredDraftGenerator(api_key="secret", base_url="https://dashscope.example/v1", model="qwen-test", timeout=1, retries=1, client=client)
        draft = await generator.generate(_request(), {}, _citations())
        assert draft["days"]
        assert attempts == 2
        await client.aclose()

    asyncio.run(scenario())


def test_dashscope_generator_retries_duplicate_verified_candidate() -> None:
    async def scenario() -> None:
        attempts = 0
        candidates = tuple(
            VerifiedPlanningCandidate(
                f"poi-{index}",
                f"Place {index}",
                "430100",
                112.9 + index / 100,
                28.2 + index / 100,
                Citation(
                    f"doc-{index}",
                    f"chunk-{index}",
                    "live_web",
                    f"https://example.com/{index}",
                    "430100",
                    "2026-08-11T00:00:00Z",
                    f"Place {index}",
                ),
            )
            for index in range(1, 4)
        )
        request = GenerationRequest(
            "job-2",
            "user-1",
            "Plan Changsha",
            "430100",
            date(2026, 9, 1),
            date(2026, 9, 1),
            verified_candidates=candidates,
        )

        async def handler(http_request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                content = '{"title":"Changsha","days":[{"date":"2026-09-01","activities":[{"poi_id":"poi-1","title":"Place 1"},{"poi_id":"poi-1","title":"Place 1"}]}]}'
            else:
                body = json.loads(http_request.content)
                assert "unique POIs" in body["messages"][-1]["content"]
                content = '{"title":"Changsha","days":[{"date":"2026-09-01","activities":[{"poi_id":"poi-1","title":"Place 1"},{"poi_id":"poi-2","title":"Place 2"},{"poi_id":"poi-3","title":"Place 3"}]}]}'
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        generator = DashScopeStructuredDraftGenerator(
            api_key="secret",
            base_url="https://dashscope.example/v1",
            model="qwen-test",
            timeout=1,
            retries=1,
            client=client,
        )
        draft = await generator.generate(request, {}, tuple(candidate.source for candidate in candidates))
        assert len(draft["days"][0]["activities"]) == 3
        assert attempts == 2
        await client.aclose()

    asyncio.run(scenario())


def test_dashscope_generator_normalizes_title_for_verified_poi_id() -> None:
    async def scenario() -> None:
        candidates = tuple(
            VerifiedPlanningCandidate(
                f"poi-{index}",
                f"Verified Place {index}",
                "430100",
                112.9 + index / 100,
                28.2 + index / 100,
                Citation(
                    f"doc-{index}",
                    f"chunk-{index}",
                    "live_web",
                    f"https://example.com/{index}",
                    "430100",
                    "2026-08-11T00:00:00Z",
                    f"Verified Place {index}",
                ),
            )
            for index in range(1, 3)
        )
        request = GenerationRequest(
            "job-3",
            "user-1",
            "Plan Changsha",
            "430100",
            date(2026, 9, 1),
            date(2026, 9, 1),
            verified_candidates=candidates,
        )

        async def handler(_: httpx.Request) -> httpx.Response:
            content = '{"title":"Changsha","days":[{"date":"2026-09-01","activities":[{"poi_id":"poi-1","title":"Short name"},{"poi_id":"poi-2","title":"Another short name"}]}]}'
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        generator = DashScopeStructuredDraftGenerator(
            api_key="secret",
            base_url="https://dashscope.example/v1",
            model="qwen-test",
            timeout=1,
            retries=0,
            client=client,
        )
        draft = await generator.generate(request, {}, tuple(candidate.source for candidate in candidates))
        assert [activity["title"] for activity in draft["days"][0]["activities"]] == [
            "Verified Place 1",
            "Verified Place 2",
        ]
        await client.aclose()

    asyncio.run(scenario())
