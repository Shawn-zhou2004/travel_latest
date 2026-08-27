from __future__ import annotations

from datetime import timedelta
from math import asin, cos, radians, sin, sqrt

from app.modules.ai_agents.contracts import (
    GenerationReviewRequest,
    GenerationReviewResult,
    MapLeg,
    MapRoute,
    MapRouteRequest,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    PlannedDay,
    PlannedItinerary,
    PlannedStop,
    PlanningCandidate,
    PlanningRequest,
    RetrievalDocument,
    RetrievalRequest,
    RetrievalResult,
    ReviewIssue,
)

#ControlledRetrievalService.retrieve做同城过滤；citations 只保留被选中的 chunk
class ControlledRetrievalService:
    """Filters caller-provided reviewed documents without querying external stores."""

    def retrieve(
        self, request: RetrievalRequest, documents: tuple[RetrievalDocument, ...]
    ) -> RetrievalResult:
        selected = sorted(
            (document for document in documents if document.city_code == request.context.city_code),
            key=lambda document: (-document.score, document.chunk_id),
        )
        return RetrievalResult(query=request.query, documents=tuple(selected[: request.limit]))

#确定性过滤并限流
class ControlledMemoryRetrievalService:
    """Returns only records owned by the request user, ordered deterministically."""

    def retrieve(
        self, request: MemoryRetrievalRequest, records: tuple[MemoryRecord, ...]
    ) -> MemoryRetrievalResult:
        selected = sorted(
            (record for record in records if record.user_id == request.context.user_id),
            key=lambda record: (-record.confidence, record.memory_id),
        )
        return MemoryRetrievalResult(query=request.query, records=tuple(selected[: request.limit]))


class ControlledPlanningService:
    """Builds a fixed one-stop-per-day itinerary from verified caller candidates."""

    def plan(self, request: PlanningRequest) -> PlannedItinerary:
        candidates = tuple(
            candidate for candidate in request.candidates if candidate.city_code == request.context.city_code
        )
        if not candidates:
            raise ValueError("planning requires at least one candidate in the requested city")

        days: list[PlannedDay] = []
        current_date = request.start_date
        candidate_index = 0
        while current_date <= request.end_date:
            eligible = tuple(
                candidate
                for candidate in candidates
                if not candidate.available_on or current_date in candidate.available_on
            )
            if not eligible:
                raise ValueError(f"no candidate is available on {current_date.isoformat()}")
            selected = eligible[candidate_index % len(eligible)]
            days.append(PlannedDay(date=current_date, stops=(self._stop(selected),)))
            candidate_index += 1
            current_date += timedelta(days=1)

        return PlannedItinerary(
            city_code=request.context.city_code,
            days=tuple(days),
            total_estimated_cost=sum(stop.estimated_cost for day in days for stop in day.stops),
        )

    @staticmethod
    def _stop(candidate: PlanningCandidate) -> PlannedStop:
        return PlannedStop(
            poi_id=candidate.poi_id,
            title=candidate.title,
            estimated_cost=candidate.estimated_cost,
            evidence_chunk_id=candidate.evidence_chunk_id,
        )


class ControlledMapService:
    """Calculates straight-line route distances from caller-supplied coordinates."""

    def build_route(self, request: MapRouteRequest) -> MapRoute:
        legs = tuple(
            MapLeg(
                from_poi_id=origin.poi_id,
                to_poi_id=destination.poi_id,
                distance_meters=self._distance_meters(origin.latitude, origin.longitude, destination.latitude, destination.longitude),
            )
            for origin, destination in zip(request.points, request.points[1:])
        )
        return MapRoute(
            ordered_poi_ids=tuple(point.poi_id for point in request.points),
            legs=legs,
            total_distance_meters=sum(leg.distance_meters for leg in legs),
        )

    @staticmethod
    def _distance_meters(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> int:
        latitude_delta = radians(latitude_b - latitude_a)
        longitude_delta = radians(longitude_b - longitude_a)
        haversine = sin(latitude_delta / 2) ** 2 + cos(radians(latitude_a)) * cos(radians(latitude_b)) * sin(longitude_delta / 2) ** 2
        return round(6_371_000 * 2 * asin(sqrt(haversine)))


class GenerationReviewService:
    """Validates a generated itinerary against explicit evidence and route inputs."""

    def review(self, request: GenerationReviewRequest) -> GenerationReviewResult:
        issues: list[ReviewIssue] = []
        itinerary = request.itinerary
        planning = request.planning_request
        expected_dates = tuple(
            planning.start_date + timedelta(days=offset)
            for offset in range((planning.end_date - planning.start_date).days + 1)
        )
        if itinerary.city_code != planning.context.city_code:
            issues.append(ReviewIssue(code="ITINERARY_CITY_MISMATCH", message="Itinerary city does not match the planning request."))
        if tuple(day.date for day in itinerary.days) != expected_dates:
            issues.append(ReviewIssue(code="ITINERARY_DATE_MISMATCH", message="Itinerary days do not match the requested date range."))

        evidence_ids = {document.chunk_id for document in request.retrieval.documents}
        poi_ids: list[str] = []
        for day in itinerary.days:
            for stop in day.stops:
                poi_ids.append(stop.poi_id)
                if stop.evidence_chunk_id not in evidence_ids:
                    issues.append(ReviewIssue(code="MISSING_RETRIEVAL_EVIDENCE", message="Stop lacks retrieval evidence.", day=day.date, poi_id=stop.poi_id))
        for poi_id in sorted({poi_id for poi_id in poi_ids if poi_ids.count(poi_id) > 1}):
            issues.append(ReviewIssue(code="DUPLICATE_POI", message="POI appears more than once in the itinerary.", poi_id=poi_id))
        if request.route.ordered_poi_ids != tuple(poi_ids):
            issues.append(ReviewIssue(code="MAP_ROUTE_MISMATCH", message="Map route order does not match itinerary stops."))
        return GenerationReviewResult(approved=not issues, issues=tuple(issues))
