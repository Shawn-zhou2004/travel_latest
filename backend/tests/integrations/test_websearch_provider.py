import asyncio
import json
from datetime import UTC, datetime

import httpx

from app.integrations.mcp import (
    MagicMcpWebPageFetcher,
    MagicMcpWebSearchProvider,
    UnavailableWebSearchProvider,
    WebSearchCandidate,
    WebSearchProvider,
    chunk_web_content,
    is_knowledge_candidate_eligible,
    rank_web_search_candidates,
)


def test_magic_mcp_web_search_uses_streamable_http_mcp_and_returns_metadata_only_candidates() -> None:
    async def scenario() -> None:
        received: httpx.Request | None = None

        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal received
            received = request
            requests.append(request)
            payload = json.loads(request.content)
            if payload["method"] == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-1"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {"content": [{"type": "text", "text": json.dumps({"results": [{"url": "https://tourism.example/notice", "title": "Visitor notice", "excerpt": "Book timed entry before your visit.", "published_at": "2026-08-07T08:30:00Z"}]})}]},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider: WebSearchProvider = MagicMcpWebSearchProvider(
            endpoint="https://mcp.example/tools/call",
            tool="web_search",
            api_key="secret",
            timeout=7,
            client=client,
        )

        candidates = await provider.search("official visitor notice", limit=3)

        assert candidates[0].source_url == "https://tourism.example/notice"
        assert candidates[0].source_host == "tourism.example"
        assert candidates[0].published_at == datetime(2026, 8, 7, 8, 30, tzinfo=UTC)
        assert received is not None
        assert received.url == "https://mcp.example/tools/call"
        assert received.headers["Authorization"] == "Bearer secret"
        assert received.headers["Mcp-Session-Id"] == "session-1"
        assert json.loads(received.content) == {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "web_search", "arguments": {"query": "official visitor notice", "count": 3, "offset": 0}},
        }
        assert [json.loads(request.content)["method"] for request in requests] == ["initialize", "notifications/initialized", "tools/call"]
        await client.aclose()

    asyncio.run(scenario())


def test_magic_mcp_web_page_fetcher_reads_structured_content_text() -> None:
    from app.integrations.mcp.websearch import _fetched_text

    assert _fetched_text({
        "structuredContent": {"markdown": "怀化景点：洪江古商城、黔阳古城。"},
    }) == "怀化景点：洪江古商城、黔阳古城。"


def test_magic_mcp_web_page_fetcher_discards_robots_denial_text() -> None:
    from app.integrations.mcp.websearch import _fetched_text

    assert _fetched_text({"content": [{"type": "text", "text": "robots.txt specifies that autonomous fetching of this page is not allowed"}]}) is None


def test_magic_mcp_web_page_fetcher_returns_bounded_text_for_an_https_url() -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            payload = json.loads(request.content)
            if payload["method"] == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-1"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "Hongjiang Ancient Mall\nA historic town in Huaihua."}]}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        fetcher = MagicMcpWebPageFetcher(endpoint="https://mcp.example/mcp", tool="fetch", api_key="secret", timeout=1, client=client)

        text = await fetcher.fetch("https://tourism.example/huaihua")

        assert text == "Hongjiang Ancient Mall\nA historic town in Huaihua."
        tool_call = json.loads(requests[-1].content)
        assert tool_call["params"] == {"name": "fetch", "arguments": {"url": "https://tourism.example/huaihua"}}
        assert await fetcher.fetch("http://tourism.example/huaihua") is None
        await client.aclose()

    asyncio.run(scenario())


def test_magic_mcp_web_search_discards_invalid_or_content_bearing_candidates() -> None:
    async def scenario() -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            payload = json.loads(_.content)
            if payload["method"] == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-1"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {"content": [{"type": "text", "text": json.dumps({"results": [{"url": "http://tourism.example/a", "title": "HTTP", "excerpt": "No"}, {"url": "https://tourism.example/b", "title": "Raw", "excerpt": "No", "raw_html": "<p>no</p>"}, {"url": "https://tourism.example/c", "title": "Date", "excerpt": "No", "published_at": "not-a-date"}, {"url": "https://tourism.example/d", "title": "Too long", "excerpt": "x" * 4_001}, {"url": "https://tourism.example/e", "title": "Valid", "excerpt": "Metadata only"}]})}]},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = MagicMcpWebSearchProvider(
            endpoint="https://mcp.example/tools/call",
            tool="web_search",
            api_key="secret",
            timeout=1,
            client=client,
        )

        candidates = await provider.search("query", limit=5)

        assert [(candidate.title, candidate.source_url) for candidate in candidates] == [
            ("Valid", "https://tourism.example/e")
        ]
        await client.aclose()

    asyncio.run(scenario())


def test_magic_mcp_web_search_accepts_structured_tool_content() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if payload["method"] == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-1"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": {"webPages": {"value": [{"url": "https://tourism.example/notice", "name": "Visitor notice", "snippet": "Book timed entry before your visit."}]}}}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = MagicMcpWebSearchProvider(endpoint="https://mcp.example/mcp", tool="bing_search", api_key="secret", timeout=1, client=client)

        candidates = await provider.search("visitor notice", limit=1)

        assert [(candidate.title, candidate.excerpt) for candidate in candidates] == [
            ("Visitor notice", "Book timed entry before your visit.")
        ]
        await client.aclose()

    asyncio.run(scenario())


def test_unavailable_web_search_provider_returns_no_candidates() -> None:
    candidates = asyncio.run(UnavailableWebSearchProvider().search("query", limit=5))

    assert candidates == ()


def test_knowledge_candidate_quality_gate_requires_relevant_public_sources() -> None:
    official = WebSearchCandidate(
        source_url="https://wgly.hangzhou.gov.cn/notice",
        source_host="wgly.hangzhou.gov.cn",
        title="Hangzhou museum visitor guidance",
        excerpt="Visitor guidance for museum reservations.",
    )
    unrelated = WebSearchCandidate(
        source_url="https://zhidao.baidu.com/question/1.html",
        source_host="zhidao.baidu.com",
        title="Baidu search guide",
        excerpt="How to use a search engine.",
    )
    community = WebSearchCandidate(
        source_url="https://example.com/notes",
        source_host="example.com",
        title="West Lake slow walking notes",
        excerpt="Start early around West Lake.",
    )
    chinese_official = WebSearchCandidate(
        source_url="https://wgly.hangzhou.gov.cn/museum",
        source_host="wgly.hangzhou.gov.cn",
        title="杭州博物馆参观须知",
        excerpt="请提前预约入馆。",
    )

    assert is_knowledge_candidate_eligible(official, query="Hangzhou museum visitor guidance", target_domain="official")
    assert not is_knowledge_candidate_eligible(unrelated, query="Hangzhou museum visitor guidance", target_domain="official")
    assert is_knowledge_candidate_eligible(community, query="West Lake walking", target_domain="community")
    assert not is_knowledge_candidate_eligible(community, query="Hangzhou museum visitor guidance", target_domain="community")
    assert is_knowledge_candidate_eligible(chinese_official, query="杭州博物馆开放时间", target_domain="official")


def test_live_search_candidates_are_ranked_and_deduplicated() -> None:
    candidates = (
        WebSearchCandidate("https://example.com/a", "example.com", "怀化概况", "怀化城市介绍"),
        WebSearchCandidate("https://tourism.gov.cn/a", "tourism.gov.cn", "怀化景区推荐", "洪江古商城和黔阳古城景点"),
        WebSearchCandidate("https://tourism.gov.cn/b", "tourism.gov.cn", "怀化景区推荐", "重复结果"),
    )

    ranked = rank_web_search_candidates("怀化有什么好玩的地方吗", candidates)

    assert ranked[0].source_host == "tourism.gov.cn"
    assert len(ranked) == 2
    chunks = chunk_web_content("  洪江古商城\n\n黔阳古城  ", chunk_size=4)
    assert "".join(chunks) == "洪江古商城 黔阳古城"
