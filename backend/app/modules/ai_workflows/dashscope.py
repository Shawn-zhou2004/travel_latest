from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import httpx

from app.modules.ai_workflows.contracts import Citation, GenerationRequest, VerifiedPlanningCandidate
from app.modules.ai_workflows.workflow import DependencyUnavailable


class DashScopeStructuredDraftGenerator:
    """DashScope adapter for its OpenAI-compatible chat completions API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        retries: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key or not base_url or not model:
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
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def generate(
        self,
        request: GenerationRequest,
        profile_memory: Mapping[str, object],
        citations: tuple[Citation, ...],
    ) -> Mapping[str, object]:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                    "content": (
                    "Produce an itinerary draft as a JSON object only. Use factual POI names, "
                    "poi_id values, titles, and costs only when supported by the supplied verified_candidates. "
                    "Do not invent facts, POIs, or sources. The JSON object must contain only "
                    "title and days. For a targeted modification, return the complete itinerary, "
                    "including unchanged days and activities. Each day must contain only date and activities. Each activity "
                    "must contain a non-empty poi_id and title copied exactly from verified_candidates. "
                    "Each activity may additionally contain estimated_cost. Omit estimated_cost when the sources do not state "
                    "a cost; when present it must be a non-negative integer literal such as 0, never null, a decimal, or a currency string. "
                    "Use this exact shape: {\"title\": \"Trip title\", \"days\": [{\"date\": \"YYYY-MM-DD\", \"activities\": "
                    "[{\"poi_id\": \"verified-poi-id\", \"title\": \"Activity title\", \"estimated_cost\": 0}]}]}. "
                    "Target three unique activities per requested day; use two only when three are unavailable. "
                    "Every poi_id in must_visit_poi_ids must appear exactly once in the complete itinerary."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
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
                        "citations": [
                            {
                                "document_id": citation.document_id,
                                "chunk_id": citation.chunk_id,
                                "source_type": citation.source_type,
                                "source_id": citation.source_id,
                                "city_code": citation.city_code,
                                "source_updated_at": citation.source_updated_at,
                                "content": citation.content,
                            }
                            for citation in citations
                        ],
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
                ),
            },
        ]
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        for attempt in range(self.retries + 1):
            try:
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                draft = self._parse_response(response)
                draft = self._normalize_verified_candidate_titles(draft, request)
                self._validate_draft_shape(draft, request)
                return draft
            except (httpx.HTTPError, ValueError, TypeError) as error:
                if attempt == self.retries:
                    raise DependencyUnavailable("dashscope", "DashScope structured draft generation is unavailable") from error
                messages.append({
                    "role": "user",
                    "content": f"Your previous JSON draft was invalid: {error}. Return the complete corrected JSON object only.",
                })
                await asyncio.sleep(0)
        raise AssertionError("unreachable")

    @staticmethod
    def _parse_response(response: httpx.Response) -> Mapping[str, object]:
        payload: Any = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("DashScope returned a non-object response")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ValueError("DashScope returned no completion choices")
        message = choices[0].get("message")
        if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
            raise ValueError("DashScope returned an invalid completion message")
        draft = json.loads(message["content"])
        if not isinstance(draft, Mapping):
            raise ValueError("DashScope completion content must be a JSON object")
        return dict(draft)

    @staticmethod
    def _normalize_verified_candidate_titles(
        draft: Mapping[str, object], request: GenerationRequest
    ) -> Mapping[str, object]:
        allowed = {candidate.poi_id: candidate.poi_name for candidate in request.verified_candidates}
        if not allowed:
            return draft
        normalized = dict(draft)
        days = normalized.get("days")
        if not isinstance(days, list):
            return normalized
        normalized_days: list[object] = []
        for day in days:
            if not isinstance(day, Mapping):
                normalized_days.append(day)
                continue
            normalized_day = dict(day)
            activities = normalized_day.get("activities")
            if isinstance(activities, list):
                normalized_activities: list[object] = []
                for activity in activities:
                    if not isinstance(activity, Mapping):
                        normalized_activities.append(activity)
                        continue
                    normalized_activity = dict(activity)
                    poi_id = normalized_activity.get("poi_id")
                    if isinstance(poi_id, str) and poi_id in allowed:
                        normalized_activity["title"] = allowed[poi_id]
                    normalized_activities.append(normalized_activity)
                normalized_day["activities"] = normalized_activities
            normalized_days.append(normalized_day)
        normalized["days"] = normalized_days
        return normalized

    @staticmethod
    def _validate_draft_shape(draft: Mapping[str, object], request: GenerationRequest) -> None:
        if not isinstance(draft.get("title"), str) or not draft["title"].strip():
            raise ValueError("Draft requires a non-empty title")
        days = draft.get("days")
        expected_days = (request.end_date - request.start_date).days + 1
        if not isinstance(days, list) or len(days) != expected_days:
            raise ValueError("Draft must include one day for every requested travel date")
        allowed_candidates = {
            candidate.poi_id: candidate.poi_name for candidate in request.verified_candidates
        }
        selected_poi_ids: set[str] = set()
        for day in days:
            if not isinstance(day, Mapping) or not isinstance(day.get("date"), str) or not isinstance(day.get("activities"), list):
                raise ValueError("Each draft day requires date and activities")
            if allowed_candidates and not 2 <= len(day["activities"]) <= 3:
                raise ValueError("Each new itinerary day requires two or three activities")
            for activity in day["activities"]:
                if not isinstance(activity, Mapping) or not isinstance(activity.get("poi_id"), str) or not activity["poi_id"].strip() or not isinstance(activity.get("title"), str) or not activity["title"].strip():
                    raise ValueError("Each activity requires a non-empty poi_id and title")
                poi_id = activity["poi_id"]
                if allowed_candidates and allowed_candidates.get(poi_id) != activity["title"]:
                    raise ValueError("Each activity must copy a POI ID and title from verified_candidates")
                if allowed_candidates and poi_id in selected_poi_ids:
                    raise ValueError("Draft activities must use unique POIs")
                selected_poi_ids.add(poi_id)
