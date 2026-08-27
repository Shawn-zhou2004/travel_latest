from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping, Protocol
from zoneinfo import ZoneInfo

import httpx


TransportType = Literal["train", "flight"]
_MCP_PROTOCOL_VERSION = "2025-03-26"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_TRAIN_RESULTS = 50
_SOLD_OUT_MARKERS = frozenset({"", "0", "--", "无", "候补", "售罄", "sold out", "unavailable", "none", "n/a"})
_STATION_TELECODE = re.compile(r"(?<![A-Z])[A-Z]{3}(?![A-Z])")


@dataclass(frozen=True)
class TransportOfferSearchRequest:
    origin: str
    destination: str
    depart_date: date
    passenger_count: int

    def __post_init__(self) -> None:
        if not self.origin.strip() or not self.destination.strip():
            raise ValueError("origin and destination are required")
        if self.passenger_count < 1:
            raise ValueError("passenger_count must be positive")


@dataclass(frozen=True)
class TransportOffer:
    source: str
    external_offer_id: str
    transport_type: TransportType
    origin: str
    destination: str
    carrier_number: str
    seat_or_cabin_class: str
    availability: Literal["available", "unavailable"]
    amount: Decimal
    currency: str
    departure_at: datetime
    arrival_at: datetime
    valid_until: datetime
    retrieved_at: datetime
    change_rules: Mapping[str, object]


@dataclass(frozen=True)
class TransportOfferResult:
    available: bool
    code: str
    message: str
    offers: tuple[TransportOffer, ...] = ()


@dataclass(frozen=True)
class OfferValidation:
    valid: bool
    code: str
    message: str
    offer: TransportOffer | None = None


class TrainOfferProvider(Protocol):
    async def search(self, request: TransportOfferSearchRequest) -> TransportOfferResult: ...


class FlightOfferProvider(Protocol):
    async def search(self, request: TransportOfferSearchRequest) -> TransportOfferResult: ...


class TransportOfferProvider(Protocol):
    async def revalidate(self, selected_offer: TransportOffer) -> OfferValidation: ...


@dataclass(frozen=True)
class MagicMcpTransportConfig:
    train_url: str | None
    train_tool: str | None
    flight_url: str | None
    flight_tool: str | None
    api_key: str | None
    timeout_seconds: float = 15.0


class UnavailableTransportOfferProvider:
    async def search(self, request: TransportOfferSearchRequest) -> TransportOfferResult:
        return _unavailable_result()

    async def revalidate(self, selected_offer: TransportOffer) -> OfferValidation:
        return _unavailable_validation()


class UnavailableTrainOfferProvider(UnavailableTransportOfferProvider):
    pass


class UnavailableFlightOfferProvider(UnavailableTransportOfferProvider):
    pass


class MagicTrainOfferProvider:
    def __init__(self, config: MagicMcpTransportConfig, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._provider = _MagicTransportOfferProvider("train", config, http_client=http_client)

    async def search(self, request: TransportOfferSearchRequest) -> TransportOfferResult:
        return await self._provider.search(request)

    async def revalidate(self, selected_offer: TransportOffer) -> OfferValidation:
        return await self._provider.revalidate(selected_offer)


class MagicFlightOfferProvider:
    def __init__(self, config: MagicMcpTransportConfig, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._provider = _MagicTransportOfferProvider("flight", config, http_client=http_client)

    async def search(self, request: TransportOfferSearchRequest) -> TransportOfferResult:
        return await self._provider.search(request)

    async def revalidate(self, selected_offer: TransportOffer) -> OfferValidation:
        return await self._provider.revalidate(selected_offer)


class _MagicTransportOfferProvider:
    def __init__(self, transport_type: TransportType, config: MagicMcpTransportConfig, *, http_client: httpx.AsyncClient | None) -> None:
        self._transport_type = transport_type
        self._url = config.train_url if transport_type == "train" else config.flight_url
        self._tool = config.train_tool if transport_type == "train" else config.flight_tool
        self._api_key = config.api_key
        self._timeout_seconds = config.timeout_seconds
        self._http_client = http_client

    async def search(self, request: TransportOfferSearchRequest) -> TransportOfferResult:
        if not self._configured():
            return _unavailable_result()
        try:
            if self._transport_type == "train":
                offers = _train_offers(await self._get_tickets(request), request)
            else:
                offers = _flight_offers(await self._search_flights(request), request)
        except (httpx.HTTPError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            return _unavailable_result()
        return TransportOfferResult(True, "OK", "Transport offers retrieved.", offers)

    async def revalidate(self, selected_offer: TransportOffer) -> OfferValidation:
        if selected_offer.transport_type != self._transport_type or not self._configured():
            return _unavailable_validation()
        try:
            if self._transport_type == "train":
                request = TransportOfferSearchRequest(
                    selected_offer.origin,
                    selected_offer.destination,
                    selected_offer.departure_at.astimezone(_SHANGHAI).date(),
                    1,
                )
                current = next(
                    offer for offer in _train_offers(await self._get_tickets(request), request)
                    if offer.external_offer_id == selected_offer.external_offer_id
                )
            else:
                payload = await self._call_tool("check_flight_seats", {"routing_id": selected_offer.external_offer_id})
                current = _validated_flight_offer(payload, selected_offer)
        except (httpx.HTTPError, RuntimeError, StopIteration, TypeError, ValueError, json.JSONDecodeError):
            return _unavailable_validation()
        if not _same_offer(current, selected_offer):
            return OfferValidation(False, "OFFER_CHANGED", "The selected transport offer has changed.", current)
        return OfferValidation(True, "OK", "The selected transport offer is still valid.", current)

    def _configured(self) -> bool:
        return bool(self._url and self._tool and self._api_key and self._timeout_seconds > 0)

    async def _get_tickets(self, request: TransportOfferSearchRequest) -> Mapping[str, Any]:
        from_station = await self._station_telecode(request.origin)
        to_station = await self._station_telecode(request.destination)
        return await self._call_tool(self._tool, {
            "date": request.depart_date.isoformat(),
            "fromStation": from_station,
            "toStation": to_station,
            "format": "json",
            "limitedNum": min(max(request.passenger_count, 1), _MAX_TRAIN_RESULTS),
        })

    async def _station_telecode(self, station_name: str) -> str:
        result = await self._call_tool_result("get-station-code-by-names", {"stationNames": [station_name]})
        return _station_telecode(result)

    async def _search_flights(self, request: TransportOfferSearchRequest) -> Mapping[str, Any]:
        return await self._call_tool(self._tool, {
            "from_city": request.origin,
            "to_city": request.destination,
            "from_date": request.depart_date.isoformat(),
            "adult_number": request.passenger_count,
            "child_number": 0,
            "cabin_grade": "ECONOMY",
            "trip_type": "ONE_WAY",
        })

    async def _call_tool(self, tool: str | None, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return _tool_payload(await self._call_tool_result(tool, arguments))

    async def _call_tool_result(self, tool: str | None, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if not tool:
            raise RuntimeError("Streamable HTTP MCP tool is not configured")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": _MCP_PROTOCOL_VERSION,
        }
        client, close_client = self._client()
        try:
            initialized = await self._request(client, headers, 1, "initialize", {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ai-travel-platform", "version": "1.0"},
            })
            session_id = initialized.headers.get("mcp-session-id")
            if not session_id:
                raise RuntimeError("Streamable HTTP MCP initialize response omitted mcp-session-id")
            headers["Mcp-Session-Id"] = session_id
            notification = await client.post(
                self._url,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                timeout=self._timeout_seconds,
            )
            notification.raise_for_status()
            response = await self._request(client, headers, 2, "tools/call", {
                "name": tool,
                "arguments": dict(arguments),
            })
            return _mcp_result(response)
        finally:
            if close_client:
                await client.aclose()

    def _client(self) -> tuple[httpx.AsyncClient, bool]:
        if self._http_client is not None:
            return self._http_client, False
        return httpx.AsyncClient(timeout=self._timeout_seconds), True

    async def _request(self, client: httpx.AsyncClient, headers: Mapping[str, str], request_id: int, method: str, params: Mapping[str, Any]) -> httpx.Response:
        response = await client.post(
            self._url,
            headers=dict(headers),
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response


def _mcp_result(response: httpx.Response) -> Mapping[str, Any]:
    payload = _response_payload(response)
    if not isinstance(payload, Mapping):
        raise RuntimeError("Streamable HTTP MCP returned an invalid JSON-RPC response")
    if isinstance(payload.get("error"), Mapping):
        raise RuntimeError("Streamable HTTP MCP tool call failed")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise RuntimeError("Streamable HTTP MCP tool call omitted a result")
    return result


def _response_payload(response: httpx.Response) -> Any:
    if "text/event-stream" not in response.headers.get("content-type", ""):
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
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str):
                payload = json.loads(block["text"])
                if isinstance(payload, Mapping):
                    return payload
    raise ValueError("MCP tool response omitted structured ticket data")


def _station_telecode(result: Mapping[str, Any]) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        raise ValueError("MCP station resolver response omitted text")
    text = "\n".join(
        block["text"]
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ).strip()
    if not text:
        raise ValueError("MCP station resolver response omitted text")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = text
    if _station_resolver_error(payload):
        raise ValueError("MCP station resolver returned an error")
    codes = set(_station_telecodes(payload))
    if len(codes) != 1:
        raise ValueError("MCP station resolver returned an ambiguous station code")
    return codes.pop()


def _station_resolver_error(payload: object) -> bool:
    if isinstance(payload, str):
        return bool(re.search(r"\b(?:error|failed?|unavailable)\b|错误|失败|不可用", payload, re.IGNORECASE))
    if isinstance(payload, Mapping):
        return any(
            key.casefold() in {"error", "errors", "errmsg", "error_message"}
            or (key.casefold() in {"success", "ok"} and value is False)
            for key, value in payload.items()
        ) or any(_station_resolver_error(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_station_resolver_error(value) for value in payload)
    return False


def _station_telecodes(payload: object) -> tuple[str, ...]:
    if isinstance(payload, str):
        return tuple(_STATION_TELECODE.findall(payload))
    if isinstance(payload, Mapping):
        return tuple(code for value in payload.values() for code in _station_telecodes(value))
    if isinstance(payload, list):
        return tuple(code for value in payload for code in _station_telecodes(value))
    return ()


def _train_offers(payload: Mapping[str, Any], request: TransportOfferSearchRequest) -> tuple[TransportOffer, ...]:
    if isinstance(payload.get("error"), Mapping):
        raise ValueError("12306 returned an error result")
    data = payload.get("data", payload)
    if isinstance(data, Mapping):
        status = data.get("status", payload.get("status"))
        rows = data.get("result")
    else:
        status = payload.get("status")
        rows = data
    if status not in (None, True, 0, "0", "success"):
        raise ValueError("12306 returned an error result")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("12306 result is malformed")
    now = datetime.now(timezone.utc)
    offers: list[TransportOffer] = []
    for row in rows:
        train_no = _required_text(row, "train_no")
        carrier = _required_text(row, "start_train_code")
        departure_at = _china_timestamp(_required_text(row, "start_date", "start_train_date"), _required_text(row, "start_time"))
        arrival_at = _china_timestamp(_required_text(row, "arrive_date"), _required_text(row, "arrive_time"))
        if arrival_at <= departure_at:
            raise ValueError("invalid train schedule")
        prices = row.get("price", row.get("prices"))
        if not isinstance(prices, list) or not all(isinstance(price, Mapping) for price in prices):
            raise ValueError("12306 ticket prices are malformed")
        for price in prices:
            seat_type_code = _required_text(price, "seat_type_code")
            offers.append(TransportOffer(
                source="magic_mcp",
                external_offer_id=f"{train_no}:{seat_type_code}",
                transport_type="train",
                origin=request.origin,
                destination=request.destination,
                carrier_number=carrier,
                seat_or_cabin_class=_required_text(price, "seat_name"),
                availability=_availability(price.get("num")),
                amount=_amount(price.get("price")),
                currency="CNY",
                departure_at=departure_at,
                arrival_at=arrival_at,
                valid_until=now + timedelta(minutes=5),
                retrieved_at=now,
                change_rules={},
            ))
    return tuple(offers)


def _flight_offers(payload: Mapping[str, Any], request: TransportOfferSearchRequest) -> tuple[TransportOffer, ...]:
    data = _flight_data(payload)
    rows = data if isinstance(data, list) else _flight_rows(data)
    now = datetime.now(timezone.utc)
    return tuple(_flight_offer(row, request, now) for row in rows)


def _validated_flight_offer(payload: Mapping[str, Any], selected: TransportOffer) -> TransportOffer:
    data = _flight_data(payload)
    if isinstance(data, Mapping) and _is_availability_only(data):
        availability = _required_availability(data)
        if availability != "available":
            raise ValueError("flight is unavailable")
        return TransportOffer(
            source=selected.source,
            external_offer_id=selected.external_offer_id,
            transport_type=selected.transport_type,
            origin=selected.origin,
            destination=selected.destination,
            carrier_number=selected.carrier_number,
            seat_or_cabin_class=selected.seat_or_cabin_class,
            availability=availability,
            amount=selected.amount,
            currency=selected.currency,
            departure_at=selected.departure_at,
            arrival_at=selected.arrival_at,
            valid_until=_valid_until(data, datetime.now(timezone.utc)),
            retrieved_at=datetime.now(timezone.utc),
            change_rules=selected.change_rules,
        )
    rows = data if isinstance(data, list) else _flight_rows(data)
    current = next(offer for offer in _flight_offers({"data": rows}, TransportOfferSearchRequest(
        selected.origin, selected.destination, selected.departure_at.date(), 1,
    )) if offer.external_offer_id == selected.external_offer_id)
    return current


def _flight_data(payload: Mapping[str, Any]) -> list[Any] | Mapping[str, Any]:
    data = payload.get("data")
    if isinstance(data, str):
        data = json.loads(data)
    if isinstance(data, (list, Mapping)):
        return data
    raise ValueError("flight result is malformed")


def _flight_rows(data: Mapping[str, Any]) -> list[Any]:
    for key in ("offers", "flights", "routings"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
    raise ValueError("flight result omitted offers")


def _flight_offer(row: Any, request: TransportOfferSearchRequest, now: datetime) -> TransportOffer:
    if not isinstance(row, Mapping):
        raise ValueError("flight offer is malformed")
    departure_at = _aware_timestamp(_required_text(row, "departure_at", "departure_time"))
    arrival_at = _aware_timestamp(_required_text(row, "arrival_at", "arrival_time"))
    if arrival_at <= departure_at:
        raise ValueError("invalid flight schedule")
    return TransportOffer(
        source="magic_mcp",
        external_offer_id=_required_text(row, "routing_id", "id"),
        transport_type="flight",
        origin=request.origin,
        destination=request.destination,
        carrier_number=_required_text(row, "flight_number", "carrier_number", "number"),
        seat_or_cabin_class=_required_text(row, "class", "cabin_grade", "seat_or_cabin_class"),
        availability=_required_availability(row),
        amount=_amount(row.get("amount", row.get("price"))),
        currency=_currency(row.get("currency")),
        departure_at=departure_at,
        arrival_at=arrival_at,
        valid_until=_valid_until(row, now),
        retrieved_at=now,
        change_rules={},
    )


def _is_availability_only(data: Mapping[str, Any]) -> bool:
    return set(data).issubset({"availability", "available", "valid_until"}) and (
        "availability" in data or "available" in data
    )


def _required_availability(item: Mapping[str, Any]) -> Literal["available", "unavailable"]:
    value = item.get("availability", item.get("available"))
    if isinstance(value, bool):
        return "available" if value else "unavailable"
    if isinstance(value, str) and value.strip().casefold() in {"available", "unavailable"}:
        return value.strip().casefold()  # type: ignore[return-value]
    raise ValueError("missing or invalid availability")


def _currency(value: object) -> str:
    if isinstance(value, str) and len(value.strip()) == 3 and value.strip().isalpha():
        return value.strip().upper()
    raise ValueError("invalid currency")


def _aware_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid flight timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("flight timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _valid_until(item: Mapping[str, Any], now: datetime) -> datetime:
    value = item.get("valid_until")
    if isinstance(value, str):
        try:
            return _aware_timestamp(value)
        except ValueError:
            pass
    return now + timedelta(minutes=5)


def _same_offer(current: TransportOffer, selected: TransportOffer) -> bool:
    return (
        current.external_offer_id == selected.external_offer_id
        and current.transport_type == selected.transport_type
        and current.origin == selected.origin
        and current.destination == selected.destination
        and current.carrier_number == selected.carrier_number
        and current.seat_or_cabin_class == selected.seat_or_cabin_class
        and current.availability == selected.availability == "available"
        and current.amount == selected.amount
        and current.currency == selected.currency
        and current.departure_at == selected.departure_at
        and current.arrival_at == selected.arrival_at
    )


def _required_text(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"missing {keys[0]}")


def _availability(value: object) -> Literal["available", "unavailable"]:
    text = value.strip().casefold() if isinstance(value, str) else str(value).strip().casefold() if value is not None else ""
    return "unavailable" if text in _SOLD_OUT_MARKERS else "available"


def _amount(value: object) -> Decimal:
    text = value.strip().removeprefix("CNY").removeprefix("¥").strip() if isinstance(value, str) else str(value)
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError("invalid price") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid price")
    return amount


def _china_timestamp(date_value: str, time_value: str) -> datetime:
    try:
        parsed_date = date.fromisoformat(date_value) if "-" in date_value else datetime.strptime(date_value, "%Y%m%d").date()
        parsed_time = datetime.strptime(time_value, "%H:%M").time() if len(time_value) == 5 else datetime.strptime(time_value, "%H:%M:%S").time()
    except ValueError:
        raise ValueError("invalid 12306 schedule") from None
    return datetime.combine(parsed_date, parsed_time, _SHANGHAI).astimezone(timezone.utc)


def _unavailable_result() -> TransportOfferResult:
    return TransportOfferResult(False, "REALTIME_TRANSPORT_UNAVAILABLE", "Real-time transport offers are unavailable.")


def _unavailable_validation() -> OfferValidation:
    return OfferValidation(False, "REALTIME_TRANSPORT_UNAVAILABLE", "Real-time transport offer validation is unavailable.")
