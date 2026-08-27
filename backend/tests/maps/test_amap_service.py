import asyncio

import httpx

from app.modules.maps.service import AMapService, MapRoute, MapUnavailable


def test_search_pois_normalizes_amap_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v5/place/text")
        assert request.url.params["keywords"] == "西湖"
        return httpx.Response(200, json={
            "status": "1",
            "pois": [{
                "id": "B001",
                "name": "西湖风景名胜区",
                "address": "西湖区",
                "location": "120.1302,30.2400",
                "cityname": "杭州市",
                "type": "风景名胜",
            }],
        })

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
            pois = await AMapService(api_key="test-key", client=client).search_pois("西湖")
        assert len(pois) == 1
        assert pois[0].id == "B001"
        assert pois[0].location == (120.1302, 30.24)

    asyncio.run(scenario())


def test_verify_poi_returns_unavailable_when_amap_has_no_match() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v5/place/detail")
        return httpx.Response(200, json={"status": "1", "pois": []})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
            result = await AMapService(api_key="test-key", client=client).verify_poi("missing")
        assert isinstance(result, MapUnavailable)

    asyncio.run(scenario())


def test_plan_driving_route_normalizes_polyline() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v5/direction/driving")
        return httpx.Response(200, json={
            "status": "1",
            "route": {"paths": [{
                "distance": "1200",
                "cost": {"duration": "300"},
                "steps": [{"polyline": "120.1,30.2;120.2,30.3"}, {"polyline": "120.2,30.3;120.3,30.4"}],
            }]},
        })

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
            route = await AMapService(api_key="test-key", client=client).plan_driving_route((120.1, 30.2), (120.3, 30.4))
        assert isinstance(route, MapRoute)
        assert route.distance_meters == 1200
        assert route.duration_seconds == 300
        assert route.polyline == ((120.1, 30.2), (120.2, 30.3), (120.3, 30.4))

    asyncio.run(scenario())


def test_current_weather_resolves_city_name_and_formats_live_text() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/config/district"):
            assert request.url.params["keywords"] == "长沙"
            return httpx.Response(200, json={
                "status": "1",
                "districts": [
                    {"name": "长沙县", "adcode": "430121", "level": "district"},
                    {"name": "长沙市", "adcode": "430100", "level": "city"},
                ],
            })
        assert request.url.params["city"] == "430100"
        assert request.url.params["extensions"] == "base"
        return httpx.Response(200, json={
            "status": "1",
            "lives": [{
                "province": "湖南", "city": "长沙市", "weather": "阴", "temperature": "28",
                "winddirection": "西北", "windpower": "≤3", "humidity": "86",
                "reporttime": "2026-08-19 19:02:56",
            }],
        })

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
            text = await AMapService(api_key="test-key", client=client).current_weather("长沙")
        assert text is not None
        assert "长沙市" in text
        assert "阴" in text
        assert "28" in text
        assert calls[-1].endswith("/weather/weatherInfo")

    asyncio.run(scenario())


def test_current_weather_accepts_adcode_directly() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.path.endswith("/weather/weatherInfo")
        assert request.url.params["city"] == "430100"
        return httpx.Response(200, json={
            "status": "1",
            "lives": [{
                "province": "湖南", "city": "长沙市", "weather": "多云", "temperature": "30",
                "winddirection": "南", "windpower": "3", "humidity": "70",
                "reporttime": "2026-08-19 20:00:00",
            }],
        })

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
            text = await AMapService(api_key="test-key", client=client).current_weather("430100")
        assert text is not None
        assert "多云" in text
        assert len(calls) == 1

    asyncio.run(scenario())


def test_weather_forecast_formats_daily_casts() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/weather/weatherInfo")
        assert request.url.params["extensions"] == "all"
        return httpx.Response(200, json={
            "status": "1",
            "forecasts": [{
                "city": "长沙市",
                "reporttime": "2026-08-19 19:02:56",
                "casts": [
                    {"date": "2026-08-19", "week": "3", "dayweather": "雷阵雨", "nightweather": "多云",
                     "daytemp": "35", "nighttemp": "26", "daywind": "南", "daypower": "≤3"},
                    {"date": "2026-08-20", "week": "4", "dayweather": "晴", "nightweather": "晴",
                     "daytemp": "36", "nighttemp": "27", "daywind": "南", "daypower": "≤3"},
                ],
            }],
        })

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
            text = await AMapService(api_key="test-key", client=client).weather_forecast("430100", days=4)
        assert text is not None
        assert "长沙市天气预报" in text
        assert "2026-08-19" in text
        assert "雷阵雨" in text
        assert "2026-08-20" in text

    asyncio.run(scenario())


def test_weather_returns_none_when_amap_reports_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "0", "info": "INVALID_USER_KEY"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
            service = AMapService(api_key="test-key", client=client)
            assert await service.current_weather("长沙") is None
            assert await service.weather_forecast("长沙", days=3) is None

    asyncio.run(scenario())


def test_weather_returns_none_without_api_key() -> None:
    async def scenario() -> None:
        service = AMapService(api_key="")
        assert await service.current_weather("长沙") is None
        assert await service.weather_forecast("长沙", days=3) is None

    asyncio.run(scenario())
