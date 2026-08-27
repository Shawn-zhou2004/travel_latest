from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.modules.ai_safety import AiPlanningRequest, RetrievedSource, validate_planning_output
from app.modules.ai_safety.validation import PlanningSafetyCode, unavailable_planning_result


@pytest.fixture
def planning_request() -> AiPlanningRequest:
    return AiPlanningRequest(city_code="shanghai", request="Plan a food-focused weekend.")


@pytest.fixture
def source() -> RetrievedSource:
    return RetrievedSource(
        source_id="amap-poi-1",
        source_type="amap",
        city_code="shanghai",
        status="verified",
        source_updated_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )


@pytest.fixture
def valid_draft() -> dict[str, object]:
    return {
        "kind": "itinerary_preview",
        "preview_only": True,
        "confirmation_required": True,
        "city_code": "shanghai",
        "title": "Shanghai food weekend",
        "confidence": 0.85,
        "citations": [{"citation_id": "c1", "source_id": "amap-poi-1", "claim": "Source-backed dining stop."}],
        "days": [{"events": [{"title": "Lunch", "description": "Visit the suggested dining stop.", "citation_ids": ["c1"]}]}],
    }


def test_invalid_structured_output_degrades_to_clarification(planning_request: AiPlanningRequest, source: RetrievedSource, valid_draft: dict[str, object]) -> None:
    valid_draft["write_itinerary_id"] = "not-allowed"

    result = validate_planning_output(planning_request, valid_draft, [source])

    assert result.outcome == "clarification"
    assert result.code == PlanningSafetyCode.INVALID_STRUCTURED_OUTPUT
    assert result.preview is None


def test_missing_citation_degrades_to_clarification(planning_request: AiPlanningRequest, valid_draft: dict[str, object]) -> None:
    result = validate_planning_output(planning_request, valid_draft, [])

    assert result.outcome == "clarification"
    assert result.code == PlanningSafetyCode.MISSING_CITATION


def test_untrusted_citation_degrades_to_clarification(planning_request: AiPlanningRequest, valid_draft: dict[str, object]) -> None:
    untrusted = RetrievedSource.model_construct(
        source_id="amap-poi-1",
        source_type="amap",
        city_code="shanghai",
        status="unreviewed",
        source_updated_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )

    result = validate_planning_output(planning_request, valid_draft, [untrusted])

    assert result.outcome == "clarification"
    assert result.code == PlanningSafetyCode.UNTRUSTED_CITATION


def test_city_mismatch_degrades_to_clarification(planning_request: AiPlanningRequest, source: RetrievedSource, valid_draft: dict[str, object]) -> None:
    valid_draft["city_code"] = "beijing"

    result = validate_planning_output(planning_request, valid_draft, [source])

    assert result.outcome == "clarification"
    assert result.code == PlanningSafetyCode.CITY_MISMATCH


def test_low_confidence_degrades_to_clarification(planning_request: AiPlanningRequest, source: RetrievedSource, valid_draft: dict[str, object]) -> None:
    valid_draft["confidence"] = 0.69

    result = validate_planning_output(planning_request, valid_draft, [source])

    assert result.outcome == "clarification"
    assert result.code == PlanningSafetyCode.LOW_CONFIDENCE


def test_valid_preview_is_returned_for_confirmation(planning_request: AiPlanningRequest, source: RetrievedSource, valid_draft: dict[str, object]) -> None:
    result = validate_planning_output(planning_request, valid_draft, [source])

    assert result.outcome == "preview"
    assert result.code is None
    assert result.preview is not None
    assert result.preview.preview_only is True
    assert result.preview.confirmation_required is True


def test_unavailable_result_has_no_preview() -> None:
    result = unavailable_planning_result()

    assert result.outcome == "unavailable"
    assert result.code == PlanningSafetyCode.AI_DEPENDENCY_UNAVAILABLE
    assert result.preview is None


def test_retrieved_source_rejects_untrusted_status() -> None:
    with pytest.raises(ValidationError):
        RetrievedSource(
            source_id="unknown-source",
            source_type="amap",
            city_code="shanghai",
            status="unreviewed",
            source_updated_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
