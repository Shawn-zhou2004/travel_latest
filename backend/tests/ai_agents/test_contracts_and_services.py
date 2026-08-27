from datetime import date

import pytest
from pydantic import ValidationError

from app.modules.ai_agents.contracts import (
    AgentContext,
    GenerationReviewRequest,
    MapPoint,
    MapRoute,
    MapRouteRequest,
    MemoryRecord,
    MemoryRetrievalRequest,
    PlannedDay,
    PlannedItinerary,
    PlannedStop,
    PlanningCandidate,
    PlanningRequest,
    RetrievalDocument,
    RetrievalRequest,
)
from app.modules.ai_agents.services import (
    ControlledMapService,
    ControlledMemoryRetrievalService,
    ControlledPlanningService,
    ControlledRetrievalService,
    GenerationReviewService,
)


def context() -> AgentContext:
    return AgentContext(user_id="user-1", city_code="010")


def document(chunk_id: str, *, city_code: str = "010", score: float = 0.8) -> RetrievalDocument:
    return RetrievalDocument(chunk_id=chunk_id, document_id=f"doc-{chunk_id}", city_code=city_code, content="Reviewed museum guidance", source_type="poi", source_id="poi-1", score=score)


def planning_request() -> PlanningRequest:
    return PlanningRequest(
        context=context(),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        candidates=(
            PlanningCandidate(poi_id="poi-1", title="Museum", city_code="010", estimated_cost=40, evidence_chunk_id="chunk-1"),
            PlanningCandidate(poi_id="poi-2", title="Park", city_code="010", estimated_cost=0, evidence_chunk_id="chunk-2"),
        ),
    )


def test_contracts_reject_extra_fields_invalid_coordinates_and_invalid_dates() -> None:
    with pytest.raises(ValidationError):
        AgentContext(user_id="user-1", city_code="010", provider="external")
    with pytest.raises(ValidationError):
        MapPoint(poi_id="poi", longitude=181, latitude=0)
    with pytest.raises(ValidationError, match="end_date must not precede"):
        PlanningRequest(context=context(), start_date=date(2026, 9, 2), end_date=date(2026, 9, 1), candidates=(planning_request().candidates[0],))


def test_retrieval_filters_city_orders_by_score_and_applies_limit() -> None:
    result = ControlledRetrievalService().retrieve(
        RetrievalRequest(context=context(), query="museum", limit=2),
        (document("chunk-z", score=0.4), document("chunk-a", score=0.9), document("other", city_code="021", score=1)),
    )

    assert result.query == "museum"
    assert [item.chunk_id for item in result.documents] == ["chunk-a", "chunk-z"]


def test_memory_retrieval_scopes_to_owner_and_orders_by_confidence() -> None:
    records = (
        MemoryRecord(memory_id="memory-z", user_id="user-1", key="diet", value="vegetarian", confidence=0.5),
        MemoryRecord(memory_id="memory-a", user_id="user-1", key="pace", value="slow", confidence=0.9),
        MemoryRecord(memory_id="private-other", user_id="user-2", key="diet", value="none", confidence=1),
    )

    result = ControlledMemoryRetrievalService().retrieve(MemoryRetrievalRequest(context=context(), query="preferences"), records)

    assert [record.memory_id for record in result.records] == ["memory-a", "memory-z"]


def test_planning_creates_date_complete_evidence_backed_itinerary() -> None:
    itinerary = ControlledPlanningService().plan(planning_request())

    assert [day.date for day in itinerary.days] == [date(2026, 9, 1), date(2026, 9, 2)]
    assert [day.stops[0].poi_id for day in itinerary.days] == ["poi-1", "poi-2"]
    assert itinerary.total_estimated_cost == 40


def test_planning_rejects_candidates_outside_requested_city() -> None:
    request = planning_request().model_copy(update={"candidates": (planning_request().candidates[0].model_copy(update={"city_code": "021"}),)})

    with pytest.raises(ValueError, match="requested city"):
        ControlledPlanningService().plan(request)


def test_map_service_returns_deterministic_straight_line_route() -> None:
    route = ControlledMapService().build_route(MapRouteRequest(points=(MapPoint(poi_id="a", longitude=116.4, latitude=39.9), MapPoint(poi_id="b", longitude=116.4, latitude=39.9))))

    assert route.ordered_poi_ids == ("a", "b")
    assert route.legs[0].distance_meters == 0
    assert route.total_distance_meters == 0


def test_generation_review_approves_consistent_structured_result() -> None:
    planning = planning_request()
    itinerary = ControlledPlanningService().plan(planning)
    retrieval = ControlledRetrievalService().retrieve(RetrievalRequest(context=context(), query="trip"), (document("chunk-1"), document("chunk-2")))
    route = ControlledMapService().build_route(MapRouteRequest(points=(MapPoint(poi_id="poi-1", longitude=116.4, latitude=39.9), MapPoint(poi_id="poi-2", longitude=116.41, latitude=39.91))))

    result = GenerationReviewService().review(GenerationReviewRequest(planning_request=planning, itinerary=itinerary, retrieval=retrieval, route=route))

    assert result.approved is True
    assert result.issues == ()


def test_generation_review_returns_structured_issues_without_repairing() -> None:
    planning = planning_request()
    invalid_itinerary = PlannedItinerary(
        city_code="021",
        days=(
            PlannedDay(date=date(2026, 9, 1), stops=(PlannedStop(poi_id="poi-1", title="Museum", estimated_cost=0, evidence_chunk_id="missing"),)),
            PlannedDay(date=date(2026, 9, 3), stops=(PlannedStop(poi_id="poi-1", title="Museum again", estimated_cost=0, evidence_chunk_id="missing"),)),
        ),
        total_estimated_cost=0,
    )
    route = MapRoute(ordered_poi_ids=("other",), legs=(), total_distance_meters=0)
    request = GenerationReviewRequest(planning_request=planning, itinerary=invalid_itinerary, retrieval=ControlledRetrievalService().retrieve(RetrievalRequest(context=context(), query="trip"), ()), route=route)

    result = GenerationReviewService().review(request)

    assert result.approved is False
    assert [issue.code for issue in result.issues] == [
        "ITINERARY_CITY_MISMATCH",
        "ITINERARY_DATE_MISMATCH",
        "MISSING_RETRIEVAL_EVIDENCE",
        "MISSING_RETRIEVAL_EVIDENCE",
        "DUPLICATE_POI",
        "MAP_ROUTE_MISMATCH",
    ]
    assert result.issues[2].day == date(2026, 9, 1)
    assert result.issues[2].poi_id == "poi-1"
