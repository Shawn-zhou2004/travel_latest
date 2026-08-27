from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from app.modules.ai_workflows.workflow import DependencyUnavailable


class SourceBackedAssistant:
    """Generates travel answers exclusively from RAG contexts supplied by the caller."""

    def __init__(self, *, api_key: str, base_url: str, model: str, timeout: float) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def answer(self, question: str, citations: list[dict[str, object]]) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer travel questions using only the supplied source excerpts. "
                        "Do not invent facts, prices, hours, routes, POIs, or source claims. "
                        "When sources contain named attractions, list those names directly. "
                        "Do not refuse merely because a source uses a ranking or list title; inspect the full excerpts first. "
                        "State uncertainty plainly when the sources do not answer the question. "
                        "Reply in the user's language as concise plain text."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"question": question, "sources": citations}, ensure_ascii=True),
                },
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
            response.raise_for_status()
            body: Any = response.json()
            text = body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise DependencyUnavailable("dashscope", "Source-backed assistant is temporarily unavailable.") from error
        if not isinstance(text, str) or not text.strip():
            raise DependencyUnavailable("dashscope", "Source-backed assistant returned an empty answer.")
        return text.strip()

    async def answer_general(self, question: str) -> str:
        """Handle conversational turns that do not require travel evidence."""
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a concise travel-planning assistant. Reply naturally in the user's language. "
                        "Do not claim current travel facts, prices, hours, routes, or availability unless sources are supplied."
                    ),
                },
                {"role": "user", "content": question},
            ],
        }
        return await self._complete(payload, "General assistant is temporarily unavailable.")

    async def answer_stream(self, question: str, citations: list[dict[str, object]]) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "stream": True,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer travel questions using only the supplied source excerpts. "
                        "Do not invent facts, prices, hours, routes, POIs, or source claims. "
                        "When sources contain named attractions, list the attraction names and briefly explain each. "
                        "A search-result ranking title is not itself a reason to refuse; use the named facts in the excerpts. "
                        "State uncertainty plainly when the sources do not answer the question. "
                        "Reply in the user's language as concise plain text."
                    ),
                },
                {"role": "user", "content": json.dumps({"question": question, "sources": citations}, ensure_ascii=True)},
            ],
        }
        emitted = False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"}, json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            break
                        body: Any = json.loads(data)
                        choices = body.get("choices") if isinstance(body, Mapping) else None
                        delta = choices[0].get("delta", {}) if isinstance(choices, list) and choices else {}
                        content = delta.get("content") if isinstance(delta, Mapping) else None
                        if isinstance(content, str) and content:
                            emitted = True
                            yield content[:2_000]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise DependencyUnavailable("dashscope", "Source-backed assistant is temporarily unavailable.") from error
        if not emitted:
            raise DependencyUnavailable("dashscope", "Source-backed assistant returned an empty answer.")

    async def answer_general_stream(self, question: str) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "stream": True,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a concise travel-planning assistant. Reply naturally in the user's language. "
                        "Do not claim current travel facts, prices, hours, routes, or availability unless sources are supplied."
                    ),
                },
                {"role": "user", "content": question},
            ],
        }
        emitted = False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"}, json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            break
                        body: Any = json.loads(data)
                        choices = body.get("choices") if isinstance(body, Mapping) else None
                        delta = choices[0].get("delta", {}) if isinstance(choices, list) and choices else {}
                        content = delta.get("content") if isinstance(delta, Mapping) else None
                        if isinstance(content, str) and content:
                            emitted = True
                            yield content[:2_000]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise DependencyUnavailable("dashscope", "General assistant is temporarily unavailable.") from error
        if not emitted:
            raise DependencyUnavailable("dashscope", "General assistant returned an empty answer.")

    async def _complete(self, payload: dict[str, object], unavailable_message: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"}, json=payload,
                )
            response.raise_for_status()
            body: Any = response.json()
            text = body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise DependencyUnavailable("dashscope", unavailable_message) from error
        if not isinstance(text, str) or not text.strip():
            raise DependencyUnavailable("dashscope", unavailable_message)
        return text.strip()
