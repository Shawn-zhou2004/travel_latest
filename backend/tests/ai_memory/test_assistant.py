from __future__ import annotations

import asyncio

import httpx

from app.modules.ai_memory.assistant import SourceBackedAssistant


def test_source_backed_assistant_sends_only_question_and_supplied_sources() -> None:
    async def scenario() -> None:
        request: httpx.Request | None = None

        async def handler(received: httpx.Request) -> httpx.Response:
            nonlocal request
            request = received
            return httpx.Response(200, json={"choices": [{"message": {"content": "Use the verified walking stop."}}]})

        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient

        class Client(original):
            def __init__(self, *args: object, **kwargs: object) -> None:
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        httpx.AsyncClient = Client  # type: ignore[assignment]
        try:
            assistant = SourceBackedAssistant(api_key="key", base_url="https://llm.example/v1", model="test", timeout=5)
            answer = await assistant.answer("Where can I walk?", [{"source_id": "poi-1", "content": "Verified walking stop."}])
        finally:
            httpx.AsyncClient = original  # type: ignore[assignment]

        assert answer == "Use the verified walking stop."
        assert request is not None
        assert request.headers["Authorization"] == "Bearer key"
        assert request.url == "https://llm.example/v1/chat/completions"
        assert b"Where can I walk?" in request.content
        assert b"Verified walking stop." in request.content

    asyncio.run(scenario())


def test_source_backed_assistant_streams_model_deltas() -> None:
    async def scenario() -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='data: {"choices":[{"delta":{"content":"A "}}]}\n\ndata: {"choices":[{"delta":{"content":"walk"}}]}\n\ndata: [DONE]\n\n',
            )

        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient

        class Client(original):
            def __init__(self, *args: object, **kwargs: object) -> None:
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        httpx.AsyncClient = Client  # type: ignore[assignment]
        try:
            assistant = SourceBackedAssistant(api_key="key", base_url="https://llm.example/v1", model="test", timeout=5)
            answer = "".join([part async for part in assistant.answer_stream("Where?", [{"content": "A route"}])])
        finally:
            httpx.AsyncClient = original  # type: ignore[assignment]

        assert answer == "A walk"

    asyncio.run(scenario())
