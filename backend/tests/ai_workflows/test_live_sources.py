from __future__ import annotations

from datetime import date

import pytest

from app.modules.ai_workflows.contracts import GenerationRequest
from app.modules.ai_workflows.live_sources import (
    LiveSourceCandidate,
    LiveSourceResolver,
    LiveSourceRetriever,
)
from app.modules.maps.service import MapPOI


def _request() -> GenerationRequest:
    return GenerationRequest("job-1", "user-1", "长沙景点", "430100", date(2026, 8, 10), date(2026, 8, 10))


def _source(name: str, url: str, excerpt: str) -> LiveSourceCandidate:
    return LiveSourceCandidate(name, url, "example.cn", excerpt)


class FakeMaps:
    async def search_pois(self, name_hint: str, city_code: str, *, types: str | None = None) -> list[MapPOI]:
        del city_code, types
        matches = {
            "岳麓山": [MapPOI("poi-yuelu", "岳麓山", "长沙", (112.9, 28.2), type_name="风景名胜", adcode="430104")],
            "橘子洲": [MapPOI("poi-juzizhou", "橘子洲", "长沙", (112.95, 28.19), type_name="风景名胜", adcode="430100")],
            "外地": [MapPOI("poi-foreign", "外地", "外地", (1, 1), type_name="风景名胜", adcode="310101")],
        }
        return matches.get(name_hint, [])


@pytest.mark.anyio
async def test_live_source_pipeline_keeps_only_same_city_verified_unique_pois() -> None:
    candidates = await LiveSourceResolver(FakeMaps()).resolve(
        _request(),
        (
            _source("岳麓山", "https://example.cn/yuelu", "长沙岳麓山游览信息"),
            _source("岳麓山", "https://example.cn/duplicate", "长沙岳麓山步行建议"),
            _source("橘子洲", "https://example.cn/juzizhou", "长沙橘子洲游览信息"),
            _source("外地", "https://example.cn/foreign", "外地信息"),
        ),
    )

    assert [item.poi_id for item in candidates] == ["poi-yuelu", "poi-juzizhou"]
    assert all(item.source.source_type == "live_web" for item in candidates)
    assert candidates[0].source.source_id == "https://example.cn/yuelu"


@pytest.mark.anyio
async def test_live_source_resolver_discovers_scenic_pois_without_web_sources() -> None:
    class ScenicMaps:
        async def search_pois(self, keywords: str, city_code: str, *, types: str | None = None) -> list[MapPOI]:
            del city_code
            if types:
                assert keywords.endswith("景点")
                return [
                    MapPOI("poi-yuelu", "岳麓山", "长沙", (112.9, 28.2), type_name="风景名胜", adcode="430104"),
                    MapPOI("poi-hotel", "酒店", "长沙", (112.91, 28.21), type_name="住宿服务", adcode="430100"),
                ]
            return []

    candidates = await LiveSourceResolver(ScenicMaps()).resolve(_request(), ())

    assert [item.poi_id for item in candidates] == ["poi-yuelu"]
    assert all(item.source.source_type == "live_web" for item in candidates)
    assert candidates[0].source.source_id == "https://restapi.amap.com/scenic/430100"


@pytest.mark.anyio
async def test_live_source_resolver_excludes_non_attraction_pois() -> None:
    class Maps:
        async def search_pois(self, _keywords: str, _city: str, *, types: str | None = None) -> list[MapPOI]:
            if types:
                return []
            return [
                MapPOI("hostel", "青年旅舍", "长沙", (112.9, 28.2), type_name="住宿服务", adcode="430100"),
                MapPOI("agency", "旅行社", "长沙", (112.91, 28.21), type_name="生活服务", adcode="430100"),
                MapPOI("museum", "湖南省博物馆", "长沙", (112.99, 28.21), type_name="科教文化服务;博物馆", adcode="430100"),
            ]

    candidates = await LiveSourceResolver(Maps()).resolve(
        _request(), (_source("长沙旅游攻略", "https://example.cn/guide", "景点推荐"),)
    )

    assert [candidate.poi_id for candidate in candidates] == ["museum"]


class FakeWebSearch:
    async def search(self, query: str, *, limit: int):
        from app.integrations.mcp.websearch import WebSearchCandidate

        assert query == "长沙景点"
        assert "430100" not in query
        assert limit == 12
        return (
            WebSearchCandidate("https://example.cn/a", "example.cn", "岳麓山", "游览信息"),
            WebSearchCandidate("https://example.cn/a", "example.cn", "重复", "重复信息"),
        )


@pytest.mark.anyio
async def test_live_retriever_uses_only_bounded_metadata_and_deduplicates_urls() -> None:
    sources = await LiveSourceRetriever(FakeWebSearch()).retrieve(_request())

    assert sources == (_source("岳麓山", "https://example.cn/a", "游览信息"),)
