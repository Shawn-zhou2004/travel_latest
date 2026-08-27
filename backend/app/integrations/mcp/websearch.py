from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import httpx

_MAX_TITLE_LENGTH = 300
_MAX_EXCERPT_LENGTH = 4_000
_MAX_FETCHED_CONTENT_LENGTH = 16_000
_FETCH_TEXT_KEYS = frozenset({"text", "content", "markdown", "body", "body_text", "page_content", "data"})
_FETCH_BLOCKED_MARKERS = (
    "robots.txt",
    "autonomous fetching of this page is not allowed",
    "failed to view the page",
)
_RAW_CONTENT_FIELDS = frozenset({"body", "body_text", "html", "raw_body", "raw_html", "raw_payload"})
_MCP_PROTOCOL_VERSION = "2025-03-26"
_LATIN_QUERY_TERM_PATTERN = re.compile(r"[A-Za-z0-9]{3,}")
_CHINESE_QUERY_TERM_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True)
class WebSearchCandidate:
    source_url: str
    source_host: str
    title: str
    excerpt: str
    published_at: datetime | None = None


class WebSearchProvider(Protocol):
    async def search(self, query: str, *, limit: int) -> tuple[WebSearchCandidate, ...]: ...


class WebPageFetcher(Protocol):
    async def fetch(self, source_url: str) -> str | None: ...


def rank_web_search_candidates(query: str, candidates: tuple[WebSearchCandidate, ...], *, limit: int = 8) -> tuple[WebSearchCandidate, ...]:
    """Rank live results by query coverage and source quality, then deduplicate them."""
    terms = _query_terms(query.casefold())
    seen: set[str] = set()
    scored: list[tuple[float, WebSearchCandidate]] = []
    for candidate in candidates:
        key = f"{candidate.source_host}|{candidate.title.casefold()}"
        if key in seen:
            continue
        seen.add(key)
        searchable = f"{candidate.title}\n{candidate.excerpt}".casefold()
        coverage = sum(1 for term in terms if term in searchable)
        score = coverage * 4.0
        if any(host in candidate.source_host for host in ("gov.cn", "amap.com", "map.baidu.com")):
            score += 3.0
        if any(term in searchable for term in ("景点", "景区", "古城", "公园", "瀑布", "峡谷", "故居", "博物馆")):
            score += 2.0
        if candidate.published_at is not None:
            score += 0.5
        scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], item[1].source_host, item[1].title))
    return tuple(candidate for _, candidate in scored[:limit])


def chunk_web_content(content: str, *, chunk_size: int = 2_000, limit: int = 8) -> tuple[str, ...]:
    """Create bounded, non-empty evidence chunks for the model context."""
    normalized = re.sub(r"\s+", " ", content).strip()
    if not normalized:
        return ()
    return tuple(normalized[index:index + chunk_size] for index in range(0, min(len(normalized), chunk_size * limit), chunk_size))


async def search_user_planning_candidates(
    provider: WebSearchProvider, query: str, *, limit: int
) -> tuple[WebSearchCandidate, ...]:
    """Return bounded validated metadata for a single user-planning search.

    Unlike administrative knowledge review, this deliberately has no domain
    eligibility policy and never retrieves a source URL.
    """
    if not 1 <= limit <= 12:
        raise ValueError("user planning search limit must be between 1 and 12")
    return await provider.search(query, limit=limit)


def is_knowledge_candidate_eligible(candidate: WebSearchCandidate, *, query: str, target_domain: str) -> bool:
    """Keep the human-review queue limited to relevant public-source metadata."""
    if target_domain == "official" and not candidate.source_host.endswith(".gov.cn"):
        return False
    normalized_query = query.casefold()
    terms = tuple(_query_terms(normalized_query))
    if not terms:
        return False
    searchable = f"{candidate.title}\n{candidate.excerpt}".casefold()
    return any(term in searchable for term in terms)


def _query_terms(query: str) -> tuple[str, ...]:
    latin_terms = _LATIN_QUERY_TERM_PATTERN.findall(query)
    chinese_terms = (
        phrase[index:index + 2]
        for phrase in _CHINESE_QUERY_TERM_PATTERN.findall(query)
        for index in range(len(phrase) - 1)
    )
    return tuple(dict.fromkeys((*latin_terms, *chinese_terms)))


class UnavailableWebSearchProvider:
    """Explicit default when no authorized web-search integration is configured."""

    async def search(self, query: str, *, limit: int) -> tuple[WebSearchCandidate, ...]:
        return ()


class UnavailableWebPageFetcher:
    async def fetch(self, source_url: str) -> str | None:
        return None


class MagicMcpWebSearchProvider:
    """Streamable HTTP MCP adapter that permits bounded source metadata only."""

    def __init__(
        self,
        *,
        endpoint: str,
        tool: str,
        api_key: str,
        timeout: float,
        client: httpx.AsyncClient,
    ) -> None:
        self._endpoint = endpoint
        self._tool = tool
        self._api_key = api_key
        self._timeout = timeout
        self._client = client

    async def search(self, query: str, *, limit: int) -> tuple[WebSearchCandidate, ...]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": _MCP_PROTOCOL_VERSION,
        }
        initialized = await self._request(
            headers,
            1,
            "initialize",
            {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ai-travel-platform", "version": "1.0"},
            },
        )
        session_id = initialized.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("Streamable HTTP MCP initialize response omitted mcp-session-id")
        headers["Mcp-Session-Id"] = session_id
        await self._notify_initialized(headers)
        payload = await self._request(
            headers,
            2,
            "tools/call",
            {"name": self._tool, "arguments": {"query": query, "count": limit, "offset": 0}},
        )
        result = _mcp_result(payload)
        candidates = (
            candidate
            for item in _candidate_items(_tool_payload(result))
            if (candidate := _validated_candidate(item)) is not None
        )
        return tuple(candidate for _, candidate in zip(range(limit), candidates))

    async def _request(
        self,
        headers: Mapping[str, str],
        request_id: int,
        method: str,
        params: Mapping[str, Any],
    ) -> httpx.Response:
        response = await self._client.post(
            self._endpoint,
            headers=dict(headers),
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response

    async def _notify_initialized(self, headers: Mapping[str, str]) -> None:
        response = await self._client.post(
            self._endpoint,
            headers=dict(headers),
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            timeout=self._timeout,
        )
        response.raise_for_status()


class MagicMcpWebPageFetcher:
    """Reads bounded page text through a configured MCP fetch tool only."""

    def __init__(self, *, endpoint: str, tool: str, api_key: str, timeout: float, client: httpx.AsyncClient) -> None:
        self._endpoint = endpoint
        self._tool = tool
        self._api_key = api_key
        self._timeout = timeout
        self._client = client

    async def fetch(self, source_url: str) -> str | None:
        parsed_url = urlparse(source_url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            return None
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": _MCP_PROTOCOL_VERSION,
        }
        initialized = await self._request(headers, 1, "initialize", {
            "protocolVersion": _MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ai-travel-platform", "version": "1.0"},
        })
        session_id = initialized.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("Streamable HTTP MCP initialize response omitted mcp-session-id")
        headers["Mcp-Session-Id"] = session_id
        notification = await self._client.post(
            self._endpoint,
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            timeout=self._timeout,
        )
        notification.raise_for_status()
        response = await self._request(headers, 2, "tools/call", {"name": self._tool, "arguments": {"url": source_url}})
        return _fetched_text(_mcp_result(response))

    async def _request(
        self, headers: Mapping[str, str], request_id: int, method: str, params: Mapping[str, Any]
    ) -> httpx.Response:
        response = await self._client.post(
            self._endpoint,
            headers=dict(headers),
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response


def _candidate_items(payload: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(payload, Mapping):
        return ()
    items = payload.get("results", payload.get("candidates"))
    if items is None:
        web_pages = payload.get("webPages")
        items = web_pages.get("value") if isinstance(web_pages, Mapping) else ()
    if not isinstance(items, list):
        return ()
    return tuple(item for item in items if isinstance(item, Mapping))


def _mcp_result(response: httpx.Response) -> Mapping[str, Any]:
    payload = _response_payload(response)
    if not isinstance(payload, Mapping):
        raise RuntimeError("Streamable HTTP MCP returned an invalid JSON-RPC response")
    error = payload.get("error")
    if isinstance(error, Mapping):
        raise RuntimeError(f"Streamable HTTP MCP tool call failed: {error.get('code', 'unknown')}")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise RuntimeError("Streamable HTTP MCP tool call omitted a result")
    return result


def _response_payload(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line.removeprefix("data:").strip())
    raise RuntimeError("Streamable HTTP MCP event stream omitted a data payload")


def _tool_payload(result: Mapping[str, Any]) -> Mapping[str, Any]:
    structured_content = result.get("structuredContent")
    if isinstance(structured_content, Mapping):
        return structured_content
    content = result.get("content")
    if not isinstance(content, list):
        return result
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if isinstance(payload, Mapping):
            return payload
    return {}


def _fetched_text(result: Mapping[str, Any]) -> str | None:
    values: list[str] = []

    def collect(value: Any, key: str | None = None) -> None:
        if sum(len(item) for item in values) >= _MAX_FETCHED_CONTENT_LENGTH:
            return
        if isinstance(value, str) and (key in _FETCH_TEXT_KEYS or key is None):
            if value.strip():
                values.append(value.strip())
            return
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                if child_key in _FETCH_TEXT_KEYS or child_key in {"structuredContent", "result"}:
                    collect(child_value, str(child_key))
            return
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping) and item.get("type") == "text":
                    collect(item.get("text"), "text")
                elif isinstance(item, (Mapping, list)):
                    collect(item)

    collect(result)
    text = "\n".join(dict.fromkeys(values)).strip()
    if any(marker in text.casefold() for marker in _FETCH_BLOCKED_MARKERS):
        return None
    return text[:_MAX_FETCHED_CONTENT_LENGTH] if text else None


def _validated_candidate(item: Mapping[str, Any]) -> WebSearchCandidate | None:
    if _RAW_CONTENT_FIELDS.intersection(item):
        return None
    source_url = item.get("source_url", item.get("url"))
    title = item.get("title", item.get("name"))
    excerpt = item.get("excerpt", item.get("snippet"))
    if not all(isinstance(value, str) for value in (source_url, title, excerpt)):
        return None
    parsed_url = urlparse(source_url)
    host = parsed_url.hostname
    if parsed_url.scheme != "https" or not host:
        return None
    if not 0 < len(title) <= _MAX_TITLE_LENGTH or not 0 < len(excerpt) <= _MAX_EXCERPT_LENGTH:
        return None
    published_value = item.get("published_at", item.get("datePublished"))
    published_at = _parse_published_at(published_value)
    if published_value is not None and published_at is None:
        return None
    return WebSearchCandidate(
        source_url=source_url,
        source_host=host.casefold(),
        title=title,
        excerpt=excerpt,
        published_at=published_at,
    )


def _parse_published_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
