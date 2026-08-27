from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.modules.ai_safety.contracts import AiPlanningRequest, PlanningDraft, RetrievedSource


MIN_PREVIEW_CONFIDENCE = 0.70


class PlanningSafetyCode(StrEnum):
    INVALID_STRUCTURED_OUTPUT = "INVALID_STRUCTURED_OUTPUT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MISSING_CITATION = "MISSING_CITATION"
    UNTRUSTED_CITATION = "UNTRUSTED_CITATION"
    CITY_MISMATCH = "CITY_MISMATCH"
    AI_DEPENDENCY_UNAVAILABLE = "AI_DEPENDENCY_UNAVAILABLE"


class PlanningValidationResult(BaseModel):
    """A UI/worker-safe result; only `preview` can contain a planning draft."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["preview", "clarification", "unavailable"]
    code: PlanningSafetyCode | None = None
    message: str
    preview: PlanningDraft | None = None

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> PlanningValidationResult:
        if self.outcome == "preview" and self.preview is None:
            raise ValueError("preview outcomes require a preview.")
        if self.outcome != "preview" and self.preview is not None:
            raise ValueError("only preview outcomes may include a preview.")
        return self


def unavailable_planning_result(message: str = "AI planning is temporarily unavailable.") -> PlanningValidationResult:
    """Use for model, retrieval, or required tool failures without fabricating a plan."""

    return PlanningValidationResult(
        outcome="unavailable",
        code=PlanningSafetyCode.AI_DEPENDENCY_UNAVAILABLE,
        message=message,
    )


def validate_planning_output(
    request: AiPlanningRequest,
    raw_output: Mapping[str, Any] | Any,
    retrieved_sources: list[RetrievedSource],
    *,
    minimum_confidence: float = MIN_PREVIEW_CONFIDENCE,
) -> PlanningValidationResult:
    """Parse and verify a model draft without writes, tool calls, or business mutations."""

    if not 0 <= minimum_confidence <= 1:
        raise ValueError("minimum_confidence must be between zero and one.")
    try:
        draft = PlanningDraft.model_validate(raw_output)
    except ValidationError:
        return _clarification(PlanningSafetyCode.INVALID_STRUCTURED_OUTPUT, "The AI response was not a valid planning preview.")

    if draft.city_code != request.city_code:
        return _clarification(PlanningSafetyCode.CITY_MISMATCH, "The AI preview is for a different city.")
    if draft.confidence < minimum_confidence:
        return _clarification(PlanningSafetyCode.LOW_CONFIDENCE, "More trip details are needed before a reliable preview can be generated.")

    sources_by_id = {source.source_id: source for source in retrieved_sources}
    for citation in draft.citations:
        source = sources_by_id.get(citation.source_id)
        if source is None:
            return _clarification(PlanningSafetyCode.MISSING_CITATION, "The AI preview contains a citation that was not retrieved.")
        if source.status not in {"approved", "verified"}:
            return _clarification(PlanningSafetyCode.UNTRUSTED_CITATION, "The AI preview cites a source that is not trusted.")
        if source.city_code != request.city_code:
            return _clarification(PlanningSafetyCode.CITY_MISMATCH, "The AI preview cites a source for a different city.")

    return PlanningValidationResult(outcome="preview", message="Preview is ready for user confirmation.", preview=draft)


def _clarification(code: PlanningSafetyCode, message: str) -> PlanningValidationResult:
    return PlanningValidationResult(outcome="clarification", code=code, message=message)
