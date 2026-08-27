from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlparse

from app.integrations.mcp.websearch import WebSearchProvider, search_user_planning_candidates
from app.modules.ai_workflows.contracts import (
    Citation,
    GenerationRequest,
    VerifiedPlanningCandidate,
)
from app.modules.maps.service import AMapService

MAX_LIVE_SOURCE_CANDIDATES = 12
_MAX_NAME_HINT_LENGTH = 160
_ATTRACTION_TYPE_HINTS = ("风景名胜", "公园", "博物馆", "纪念馆", "展览馆", "动物园", "植物园", "海滨", "海岛")
_SCENIC_TYPE_CODE = "110000"


@dataclass(frozen=True)
class LiveSourceCandidate:
    name_hint: str
    source_url: str
    source_host: str
    excerpt: str
    source_type: str = "live_web"


class LiveSourceRetriever:
    """Converts bounded MCP metadata into per-run evidence without persistence."""

    def __init__(self, provider: WebSearchProvider) -> None:
        self._provider = provider

    async def retrieve(self, request: GenerationRequest) -> tuple[LiveSourceCandidate, ...]:
        candidates = await search_user_planning_candidates(
            self._provider,
            request.prompt, limit=MAX_LIVE_SOURCE_CANDIDATES
        )
        sources: list[LiveSourceCandidate] = []
        seen_urls: set[str] = set()
        for candidate in candidates[:MAX_LIVE_SOURCE_CANDIDATES]:
            source = _source_from_metadata(candidate.title, candidate.excerpt, candidate.source_url)
            source_hash = _url_hash(source.source_url) if source is not None else ""
            if source is None or source_hash in seen_urls:
                continue
            seen_urls.add(source_hash)
            sources.append(source)
        return tuple(sources)


class LiveSourceResolver:
    def __init__(self, maps: AMapService) -> None:
        self._maps = maps

    async def resolve(
        self, request: GenerationRequest, sources: tuple[LiveSourceCandidate, ...]
    ) -> tuple[VerifiedPlanningCandidate, ...]:
        verified: list[VerifiedPlanningCandidate] = []
        seen_poi_ids: set[str] = set()
        seen_urls: set[str] = set()
        for source in sources[:MAX_LIVE_SOURCE_CANDIDATES]:
            source_hash = _url_hash(source.source_url)
            if source_hash in seen_urls:
                continue
            seen_urls.add(source_hash)
            matches = await self._maps.search_pois(source.name_hint, request.city_code)
            poi = next(
                (
                    item
                    for item in matches
                    if _is_attraction(item) and item.adcode and _city_code_matches(request.city_code, item.adcode)
                ),
                None,
            )
            if poi is None or poi.id in seen_poi_ids:
                continue
            seen_poi_ids.add(poi.id)
            verified.append(
                VerifiedPlanningCandidate(
                    poi_id=poi.id,
                    poi_name=poi.name,
                    city_code=poi.adcode or request.city_code,
                    longitude=poi.location[0],
                    latitude=poi.location[1],
                    source=_citation_for(source, request.city_code),
                )
            )
        # MCP article titles are often generic. Use the target city and preference
        # query to ask AMap for scenic POIs, while retaining a task-local web citation.
        # This also runs without web sources so a dead search MCP cannot starve
        # the candidate pool.
        scenic_matches = await self._maps.search_pois(
            f"{request.prompt} 景点", request.city_code, types=_SCENIC_TYPE_CODE
        )
        source = sources[0] if sources else _scenic_fallback_source(request.city_code)
        for poi in scenic_matches:
            if poi.id in seen_poi_ids or not _is_attraction(poi):
                continue
            if not poi.adcode or not _city_code_matches(request.city_code, poi.adcode):
                continue
            seen_poi_ids.add(poi.id)
            verified.append(
                VerifiedPlanningCandidate(
                    poi_id=poi.id,
                    poi_name=poi.name,
                    city_code=poi.adcode,
                    longitude=poi.location[0],
                    latitude=poi.location[1],
                    source=_citation_for(source, request.city_code),
                )
            )
        return tuple(verified)


def _scenic_fallback_source(city_code: str) -> LiveSourceCandidate:
    """Synthetic web-source stand-in when the search MCP is unreachable."""
    return LiveSourceCandidate(
        name_hint="AMap scenic discovery",
        source_url=f"https://restapi.amap.com/scenic/{city_code}",
        source_host="restapi.amap.com",
        excerpt="Scenic POIs discovered via the AMap place search service.",
    )


def _source_from_metadata(title: str, excerpt: str, source_url: str) -> LiveSourceCandidate | None:
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    title, excerpt = title.strip(), excerpt.strip()
    if not title or not excerpt:
        return None
    name_hint = title[:_MAX_NAME_HINT_LENGTH]
    if not name_hint:
        return None
    return LiveSourceCandidate(name_hint, source_url, parsed.hostname.casefold(), excerpt)


def _citation_for(source: LiveSourceCandidate, city_code: str) -> Citation:
    digest = _url_hash(source.source_url)
    return Citation(
        document_id=f"live-web:{digest}",
        chunk_id=f"live-web:{digest[:16]}",
        source_type="live_web",
        source_id=source.source_url,
        city_code=city_code,
        source_updated_at=datetime.now(UTC).isoformat(),
        content=f"{source.name_hint}\n{source.excerpt}",
    )


def _city_code_matches(requested_city_code: str, poi_adcode: str) -> bool:
    if requested_city_code == poi_adcode:
        return True
    if len(requested_city_code) != 6 or len(poi_adcode) != 6 or not requested_city_code.endswith("00"):
        return False
    if requested_city_code[:4] == poi_adcode[:4]:
        return True
    return requested_city_code[:2] in {"11", "12", "31", "50"} and requested_city_code[:2] == poi_adcode[:2]


def _is_attraction(poi: object) -> bool:
    type_name = getattr(poi, "type_name", None)
    return isinstance(type_name, str) and any(hint in type_name for hint in _ATTRACTION_TYPE_HINTS)


def _url_hash(source_url: str) -> str:
    return sha256(source_url.encode("utf-8")).hexdigest()
