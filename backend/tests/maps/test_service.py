import httpx
import pytest

from app.modules.maps.service import AMapService


@pytest.mark.anyio
async def test_search_destinations_normalizes_city_and_district_and_ranks_exact_name_first() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/config/district"
        assert request.url.params["keywords"] == "长沙"
        return httpx.Response(200, json={
            "status": "1",
            "districts": [
                {"name": "中国", "level": "country", "districts": [
                    {"name": "湖南省", "level": "province", "districts": [
                        {"name": "长沙市", "adcode": "430100", "citycode": "430100", "level": "city", "districts": [
                            {"name": "长沙县", "adcode": "430121", "citycode": "430100", "level": "district"},
                        ]},
                    ]},
                    {"name": "吉林省", "level": "province", "districts": [
                        {"name": "长春市", "adcode": "220100", "citycode": "220100", "level": "city"},
                    ]},
                ]},
            ],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
        results = await AMapService(api_key="key", client=client).search_destinations("长沙")

    assert [(item.name, item.display_address, item.city_code) for item in results] == [
        ("长沙市", "中国 · 湖南省 · 长沙市", "430100"),
        ("长沙县", "中国 · 湖南省 · 长沙市 · 长沙县", "430100"),
        ("长春市", "中国 · 吉林省 · 长春市", "220100"),
    ]


@pytest.mark.anyio
async def test_search_destinations_resolves_district_to_city_code_and_keeps_scenic_area() -> None:
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.params["keywords"])
        if request.url.params["keywords"] == "岳麓":
            return httpx.Response(200, json={"status": "1", "districts": [
                {"name": "岳麓区", "adcode": "430104", "level": "district"},
                {"name": "中国", "level": "country", "districts": [{"name": "湖南省", "level": "province", "districts": [
                    {"name": "长沙市", "adcode": "430100", "citycode": "430100", "level": "city", "districts": [
                        {"name": "岳麓山风景名胜区", "adcode": "430104001", "citycode": "430100", "level": "street"},
                    ]},
                ]}]},
            ]})
        return httpx.Response(200, json={"status": "1", "districts": [
            {"name": "中国", "level": "country", "districts": [{"name": "湖南省", "level": "province", "districts": [
                {"name": "长沙市", "adcode": "430100", "citycode": "430100", "level": "city", "districts": [
                    {"name": "岳麓区", "adcode": "430104", "level": "district", "districts": [
                        {"name": "岳麓山风景名胜区", "adcode": "430104001", "citycode": "430100", "level": "street"},
                    ]},
                ]},
            ]}]},
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
        results = await AMapService(api_key="key", client=client).search_destinations("岳麓")

    assert requests == ["岳麓", "430104"]
    assert [(item.name, item.kind, item.city_code) for item in results] == [
        ("岳麓区", "district", "430100"),
        ("岳麓山风景名胜区", "scenic_area", "430100"),
        ("长沙市", "city", "430100"),
    ]


@pytest.mark.anyio
async def test_search_destinations_handles_amap_flat_results_with_phone_citycodes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/config/district":
            return httpx.Response(200, json={"status": "1", "districts": [
                {"name": "长沙市", "adcode": "430100", "citycode": "0731", "center": "112.9,28.2", "level": "city", "districts": []},
                {"name": "长沙县", "adcode": "430121", "citycode": "0731", "center": "113.0,28.1", "level": "district", "districts": []},
            ]})
        assert request.url.path == "/v3/geocode/regeo"
        district = "长沙县" if request.url.params["location"] == "113.0,28.1" else "岳麓区"
        return httpx.Response(200, json={"status": "1", "regeocode": {"addressComponent": {
            "province": "湖南省", "city": "长沙市", "district": district,
        }}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://restapi.amap.com") as client:
        results = await AMapService(api_key="key", client=client).search_destinations("长沙")

    assert [(item.name, item.display_address, item.city_code) for item in results] == [
        ("长沙市", "中国 · 湖南省 · 长沙市", "430100"),
        ("长沙县", "中国 · 湖南省 · 长沙市 · 长沙县", "430100"),
    ]
