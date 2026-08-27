import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.integrations.mcp.transport import (
    MagicMcpTransportConfig,
    MagicFlightOfferProvider,
    MagicTrainOfferProvider,
    TransportOfferSearchRequest,
    UnavailableFlightOfferProvider,
    UnavailableTrainOfferProvider,
)


def _config() -> MagicMcpTransportConfig:
    return MagicMcpTransportConfig("https://mcp.example.test/mcp", "get-tickets", None, None, "test-key")


def _flight_config() -> MagicMcpTransportConfig:
    return MagicMcpTransportConfig(None, None, "https://mcp.example.test/mcp", "search_flights", "test-key")


def _request() -> TransportOfferSearchRequest:
    return TransportOfferSearchRequest("HZH", "BJP", date(2026, 10, 1), 1)


def _train_request() -> TransportOfferSearchRequest:
    return TransportOfferSearchRequest("杭州东", "北京南", date(2026, 10, 1), 1)


def _tickets(*, price: str = "553.00", num: str = "有") -> dict[str, object]:
    return {"data": {"status": True, "result": [{
        "train_no": "240000G1234A",
        "start_train_code": "G1234",
        "start_date": "2026-10-01",
        "start_time": "08:00",
        "arrive_date": "2026-10-01",
        "arrive_time": "12:30",
        "price": [
            {"seat_type_code": "O", "seat_name": "Second class", "price": price, "num": num},
            {"seat_type_code": "M", "seat_name": "First class", "price": "933.00", "num": "0"},
        ],
    }]}}


def _mcp_response(tickets: dict[str, object], *, sse: bool = False) -> httpx.Response:
    payload = {"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": tickets}}
    if sse:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=f"data: {json.dumps(payload)}\n\n")
    return httpx.Response(200, json=payload)


def _station_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "jsonrpc": "2.0", "id": 2,
        "result": {"content": [{"type": "text", "text": text}]},
    })


def _flight(*, price: str = "553.00", availability: str = "available") -> dict[str, object]:
    return {"data": {"offers": [{
        "routing_id": "routing-123",
        "flight_number": "MU5123",
        "class": "ECONOMY",
        "amount": price,
        "currency": "CNY",
        "departure_at": "2026-10-01T08:00:00+08:00",
        "arrival_at": "2026-10-01T10:15:00+08:00",
        "availability": availability,
        "valid_until": "2026-10-01T01:00:00Z",
    }]}}


def test_unavailable_transport_providers_do_not_return_offers() -> None:
    train = asyncio.run(UnavailableTrainOfferProvider().search(_request()))
    flight = asyncio.run(UnavailableFlightOfferProvider().search(_request()))
    assert train.available is False
    assert train.code == "REALTIME_TRANSPORT_UNAVAILABLE"
    assert train.offers == ()
    assert flight == train


def test_train_provider_uses_streamable_http_mcp_and_maps_12306_prices() -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            method = json.loads(request.content)["method"]
            if method == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-123"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if method == "notifications/initialized":
                return httpx.Response(202)
            tool = json.loads(request.content)["params"]["name"]
            if tool == "get-station-code-by-names":
                name = json.loads(request.content)["params"]["arguments"]["stationNames"][0]
                return _station_response(json.dumps({"data": [{"station_code": {"杭州东": "HZH", "北京南": "BJP"}[name]}]}))
            return _mcp_response(_tickets(), sse=True)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = await MagicTrainOfferProvider(_config(), http_client=client).search(_train_request())
        await client.aclose()

        assert result.available is True
        assert len(result.offers) == 2
        available, unavailable = result.offers
        assert available.external_offer_id == "240000G1234A:O"
        assert available.origin == "杭州东"
        assert available.destination == "北京南"
        assert available.carrier_number == "G1234"
        assert available.seat_or_cabin_class == "Second class"
        assert available.amount == 553
        assert available.currency == "CNY"
        assert available.availability == "available"
        assert unavailable.availability == "unavailable"
        assert available.departure_at == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
        assert available.arrival_at == datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
        assert available.valid_until > datetime.now(UTC)
        assert available.valid_until <= datetime.now(UTC) + timedelta(minutes=6)
        assert [json.loads(item.content)["method"] for item in requests] == [
            "initialize", "notifications/initialized", "tools/call",
            "initialize", "notifications/initialized", "tools/call",
            "initialize", "notifications/initialized", "tools/call",
        ]
        assert all(item.headers["Authorization"] == "Bearer test-key" for item in requests)
        assert all(item.headers.get("Mcp-Session-Id") == "session-123" for item in requests if json.loads(item.content)["method"] != "initialize")
        tool_calls = [json.loads(item.content) for item in requests if json.loads(item.content)["method"] == "tools/call"]
        assert [call["params"] for call in tool_calls[:2]] == [
            {"name": "get-station-code-by-names", "arguments": {"stationNames": ["杭州东"]}},
            {"name": "get-station-code-by-names", "arguments": {"stationNames": ["北京南"]}},
        ]
        assert tool_calls[-1] == {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "get-tickets", "arguments": {"date": "2026-10-01", "fromStation": "HZH", "toStation": "BJP", "format": "json", "limitedNum": 1}},
        }
        assert "document" not in requests[-1].content.decode().lower()

    asyncio.run(scenario())


def test_train_provider_revalidates_with_get_tickets_and_rejects_changed_price() -> None:
    async def scenario() -> None:
        ticket_calls = 0
        tool_calls: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal ticket_calls
            method = json.loads(request.content)["method"]
            if method == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-123"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if method == "notifications/initialized":
                return httpx.Response(202)
            call = json.loads(request.content)
            tool_calls.append(call)
            if call["params"]["name"] == "get-station-code-by-names":
                name = call["params"]["arguments"]["stationNames"][0]
                return _station_response("杭州东: HZH" if name == "杭州东" else "北京南: BJP")
            ticket_calls += 1
            return _mcp_response(_tickets(price="553.00" if ticket_calls == 1 else "599.00"))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = MagicTrainOfferProvider(_config(), http_client=client)
        selected = (await provider.search(_train_request())).offers[0]
        validation = await provider.revalidate(selected)
        await client.aclose()

        assert validation.valid is False
        assert validation.code == "OFFER_CHANGED"
        assert validation.offer is not None
        assert validation.offer.amount == 599
        assert validation.offer.origin == "杭州东"
        assert validation.offer.destination == "北京南"
        assert [call["params"] for call in tool_calls if call["params"]["name"] == "get-station-code-by-names"] == [
            {"name": "get-station-code-by-names", "arguments": {"stationNames": ["杭州东"]}},
            {"name": "get-station-code-by-names", "arguments": {"stationNames": ["北京南"]}},
            {"name": "get-station-code-by-names", "arguments": {"stationNames": ["杭州东"]}},
            {"name": "get-station-code-by-names", "arguments": {"stationNames": ["北京南"]}},
        ]

    asyncio.run(scenario())


def test_flight_provider_uses_mcp_handshake_and_exact_search_payload() -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            method = json.loads(request.content)["method"]
            if method == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-456"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if method == "notifications/initialized":
                return httpx.Response(202)
            return _mcp_response(_flight(), sse=True)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = await MagicFlightOfferProvider(_flight_config(), http_client=client).search(_request())
        await client.aclose()

        assert result.available is True
        assert result.offers[0].external_offer_id == "routing-123"
        assert result.offers[0].departure_at == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
        assert result.offers[0].valid_until == datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
        assert [json.loads(item.content)["method"] for item in requests] == ["initialize", "notifications/initialized", "tools/call"]
        assert all(item.headers["Authorization"] == "Bearer test-key" for item in requests)
        assert all(item.headers.get("Mcp-Session-Id") == "session-456" for item in requests[1:])
        assert json.loads(requests[-1].content) == {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "search_flights", "arguments": {
                "from_city": "HZH", "to_city": "BJP", "from_date": "2026-10-01",
                "adult_number": 1, "child_number": 0, "cabin_grade": "ECONOMY", "trip_type": "ONE_WAY",
            }},
        }
        assert "document" not in requests[-1].content.decode().lower()

    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [
    {"data": {"offers": [{"routing_id": "routing-123"}]}},
    {"data": {"offers": [{**_flight()["data"]["offers"][0], "departure_at": "2026-10-01T08:00:00"}]}},  # type: ignore[index]
    {"data": {"offers": "not-an-array"}},
])
def test_flight_provider_returns_unavailable_for_malformed_results(payload: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "session-456"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        return _mcp_response(payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(MagicFlightOfferProvider(_flight_config(), http_client=client).search(_request()))
    asyncio.run(client.aclose())
    assert result.available is False
    assert result.code == "REALTIME_TRANSPORT_UNAVAILABLE"


def test_flight_provider_revalidates_availability_only_without_changing_selected_offer() -> None:
    async def scenario() -> None:
        tool_calls: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            method = json.loads(request.content)["method"]
            if method == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-456"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if method == "notifications/initialized":
                return httpx.Response(202)
            call = json.loads(request.content)
            tool_calls.append(call)
            return _mcp_response(_flight() if call["params"]["name"] == "search_flights" else {"data": {"availability": "available"}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = MagicFlightOfferProvider(_flight_config(), http_client=client)
        selected = (await provider.search(_request())).offers[0]
        validation = await provider.revalidate(selected)
        await client.aclose()

        assert validation.valid is True
        assert validation.offer is not None
        assert validation.offer.amount == selected.amount
        assert validation.offer.departure_at == selected.departure_at
        assert tool_calls[-1]["params"] == {"name": "check_flight_seats", "arguments": {"routing_id": "routing-123"}}

    asyncio.run(scenario())


def test_flight_provider_rejects_revalidation_with_changed_price() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            method = json.loads(request.content)["method"]
            if method == "initialize":
                return httpx.Response(200, headers={"mcp-session-id": "session-456"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
            if method == "notifications/initialized":
                return httpx.Response(202)
            call = json.loads(request.content)
            return _mcp_response(_flight() if call["params"]["name"] == "search_flights" else _flight(price="599.00"))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = MagicFlightOfferProvider(_flight_config(), http_client=client)
        selected = (await provider.search(_request())).offers[0]
        validation = await provider.revalidate(selected)
        await client.aclose()

        assert validation.valid is False
        assert validation.code == "OFFER_CHANGED"
        assert validation.offer is not None
        assert validation.offer.amount == 599

    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [{}, {"data": {"status": False}}, {"data": {"result": "not-an-array"}}])
def test_train_provider_returns_unavailable_for_malformed_or_error_results(payload: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "session-123"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        call = json.loads(request.content)
        if call["params"]["name"] == "get-station-code-by-names":
            return _station_response("HZH" if call["params"]["arguments"]["stationNames"] == ["杭州东"] else "BJP")
        return _mcp_response(payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(MagicTrainOfferProvider(_config(), http_client=client).search(_train_request()))
    asyncio.run(client.aclose())
    assert result.available is False
    assert result.code == "REALTIME_TRANSPORT_UNAVAILABLE"


@pytest.mark.parametrize("text", [
    '{"data": [{"station_code": "HZH"}, {"station_code": "BJP"}]}',
    '{"error": "station lookup failed", "station_code": "HZH"}',
    "error: station lookup failed (HZH)",
    "no matching station",
])
def test_train_provider_returns_unavailable_for_ambiguous_or_error_station_resolution(text: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "session-123"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        return _station_response(text)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(MagicTrainOfferProvider(_config(), http_client=client).search(_train_request()))
    asyncio.run(client.aclose())
    assert result.available is False
    assert result.code == "REALTIME_TRANSPORT_UNAVAILABLE"


def test_transport_contract_rejects_passenger_document_fields() -> None:
    with pytest.raises(TypeError):
        TransportOfferSearchRequest("HZH", "BJP", date(2026, 10, 1), 1, passenger_document_no="110101199001011234")
