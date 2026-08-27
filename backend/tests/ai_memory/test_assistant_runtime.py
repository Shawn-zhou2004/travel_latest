from __future__ import annotations

import pytest

from app.modules.ai_memory.assistant import SourceBackedAssistant
from app.modules.ai_rag.types import RagResult, RagStatus


@pytest.mark.anyio
async def test_assistant_answer_contract_requires_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answer(self: SourceBackedAssistant, question: str, citations: list[dict[str, object]]) -> str:
        assert question == "Where can I walk?"
        assert citations == [{"source_id": "poi-1", "content": "Verified walking stop."}]
        return "Use the verified walking stop."

    monkeypatch.setattr(SourceBackedAssistant, "answer", answer)
    assistant = SourceBackedAssistant(api_key="key", base_url="https://llm.example/v1", model="test", timeout=5)
    assert await assistant.answer("Where can I walk?", [{"source_id": "poi-1", "content": "Verified walking stop."}]) == "Use the verified walking stop."
    assert RagResult(RagStatus.NO_RESULTS).status == RagStatus.NO_RESULTS
