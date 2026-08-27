from dataclasses import dataclass
import re
from typing import Any, Literal

import httpx

from app.core.settings import Settings


@dataclass(frozen=True)
class MapUnavailable:
    code: str = "MAP_UNAVAILABLE"
    message: str = "Map verification is not configured."


class DestinationSearchUnavailable(Exception):
    """AMap could not complete a destination search."""


@dataclass(frozen=True)
class DestinationMatch:
    id: str
    name: str
    display_address: str
    city_code: str
    kind: Literal["city", "district", "scenic_area"]


@dataclass(frozen=True)
class MapPOI:
    id: str
    name: str
    address: str
    location: tuple[float, float]
    city: str | None = None
    type_name: str | None = None
    source_updated_at: str | None = None
    adcode: str | None = None


@dataclass(frozen=True)
class MapRoute:
    distance_meters: int
    duration_seconds: int | None
    polyline: tuple[tuple[float, float], ...]


class AMapService:
    base_url = "https://restapi.amap.com/v5/place"

    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key if api_key is not None else Settings().amap_web_service_key
        self.client = client

    async def search_pois(
        self, keywords: str, city: str | None = None, *, types: str | None = None
    ) -> list[MapPOI]:
        if not self.api_key:
            return []
        params = {"key": self.api_key, "keywords": keywords, "page_size": 12, "show_fields": "business"}
        if city:
            params["city"] = city
        if types:
            params["types"] = types
        payload = await self._get("/text", params)
        return [poi for item in payload.get("pois", []) if (poi := self._poi(item)) is not None]

    async def search_destinations(self, query: str, *, limit: int = 8) -> list[DestinationMatch]:
        if not self.api_key:
            raise DestinationSearchUnavailable()
        payload = await self._get(
            "https://restapi.amap.com/v3/config/district",
            {"key": self.api_key, "keywords": query, "subdistrict": 0, "extensions": "base"},
            raise_unavailable=True,
        )
        matches: list[DestinationMatch] = []
        for item, parents in self._district_items(payload.get("districts") or []):
            match = await self._destination_match(item, parents)
            if match is not None:
                matches.append(match)
        return self._rank_destination_matches(matches, query)[:limit]

    async def verify_poi(self, poi_id: str) -> MapPOI | MapUnavailable:
        if not self.api_key:
            return MapUnavailable()
        payload = await self._get("/detail", {"key": self.api_key, "id": poi_id})
        pois = payload.get("pois", [])
        poi = self._poi(pois[0]) if pois else None
        return poi or MapUnavailable("MAP_UNAVAILABLE", "The selected place could not be verified.")

    async def plan_driving_route(self, origin: tuple[float, float], destination: tuple[float, float]) -> MapRoute | MapUnavailable:
        if not self.api_key:
            return MapUnavailable()
        payload = await self._get("https://restapi.amap.com/v5/direction/driving", {
            "key": self.api_key,
            "origin": ",".join(str(value) for value in origin),
            "destination": ",".join(str(value) for value in destination),
            "show_fields": "cost,navi,polyline",
        })
        paths = (payload.get("route") or {}).get("paths") or []
        return self._route(paths[0]) if paths else MapUnavailable("MAP_UNAVAILABLE", "A driving route could not be calculated.")

    async def current_weather(self, city: str) -> str | None:
        """Live weather for a city name or adcode, as text for the model."""
        adcode = await self._weather_adcode(city)
        if not adcode:
            return None
        payload = await self._get("https://restapi.amap.com/v3/weather/weatherInfo", {
            "key": self.api_key, "city": adcode, "extensions": "base",
        })
        lives = payload.get("lives") or []
        if not lives:
            return None
        live = lives[0]
        return (
            f"{live.get('province', '')}{live.get('city', '')}实况：{live.get('weather', '')}，"
            f"气温 {live.get('temperature', '?')}℃，{live.get('winddirection', '')}风 "
            f"{live.get('windpower', '?')} 级，湿度 {live.get('humidity', '?')}%"
            f"（发布于 {live.get('reporttime', '')}）"
        )

    async def weather_forecast(self, city: str, *, days: int = 4) -> str | None:
        """Multi-day forecast (today plus up to three more days) as text."""
        adcode = await self._weather_adcode(city)
        if not adcode:
            return None
        payload = await self._get("https://restapi.amap.com/v3/weather/weatherInfo", {
            "key": self.api_key, "city": adcode, "extensions": "all",
        })
        forecasts = payload.get("forecasts") or []
        if not forecasts:
            return None
        forecast = forecasts[0]
        casts = forecast.get("casts") or []
        if not casts:
            return None
        lines = [f"{forecast.get('city', '')}天气预报（发布于 {forecast.get('reporttime', '')}）："]
        for cast in casts[: max(1, days)]:
            lines.append(
                f"{cast.get('date', '')}（周{cast.get('week', '?')}）：白天 {cast.get('dayweather', '')} "
                f"{cast.get('daytemp', '?')}℃，夜间 {cast.get('nightweather', '')} "
                f"{cast.get('nighttemp', '?')}℃，{cast.get('daywind', '')}风 {cast.get('daypower', '?')} 级"
            )
        return "\n".join(lines)

    async def _weather_adcode(self, city: str) -> str | None:
        """Accept a 6-digit adcode directly, or resolve a city name through the district API."""
        if not self.api_key:
            return None
        if re.fullmatch(r"\d{6}", city.strip()):
            return city.strip()
        payload = await self._get("https://restapi.amap.com/v3/config/district", {
            "key": self.api_key, "keywords": city, "subdistrict": 0, "extensions": "base",
        })
        first_any: str | None = None
        city_level: str | None = None
        for district in payload.get("districts") or []:
            adcode = district.get("adcode")
            if not isinstance(adcode, str) or not adcode:
                continue
            if first_any is None:
                first_any = adcode
            if district.get("level") in ("city", "province") and city_level is None:
                city_level = adcode
        return city_level or first_any


    async def proxy_jsapi_request(
        self, path: str, *, method: str, params: dict[str, str], content: bytes
    ) -> tuple[int, bytes, str]:
        security_js_code = Settings().amap_security_js_code
        if not security_js_code:
            return 503, b'{"status":"0","info":"MAP_UNAVAILABLE"}', "application/json"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.request(
                    method,
                    f"https://restapi.amap.com/{path.lstrip('/')}",
                    params={**params, "jscode": security_js_code},
                    content=content,
                )
            return response.status_code, response.content, response.headers.get("content-type", "application/json")
        except httpx.HTTPError:
            return 503, b'{"status":"0","info":"MAP_UNAVAILABLE"}', "application/json"

    async def _get(self, path: str, params: dict[str, Any], *, raise_unavailable: bool = False) -> dict[str, Any]:
        try:
            if self.client is not None:
                response = await self.client.get(path if path.startswith("http") else f"{self.base_url}{path}", params=params)
            else:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    response = await client.get(path if path.startswith("http") else f"{self.base_url}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == "1":
                return payload
            if raise_unavailable:
                raise DestinationSearchUnavailable()
            return {}
        except (httpx.HTTPError, ValueError):
            if raise_unavailable:
                raise DestinationSearchUnavailable() from None
            return {}

    async def _destination_match(self, item: dict[str, Any], parents: tuple[dict[str, Any], ...]) -> DestinationMatch | None:
        name = item.get("name")
        adcode = item.get("adcode")
        if not isinstance(name, str) or not name.strip() or not isinstance(adcode, str) or not adcode.isdigit():
            return None
        hierarchy = parents + (item,)
        city_code = self._city_code(hierarchy)
        if city_code is None or (item.get("level") == "district" and not any(parent.get("level") == "city" for parent in hierarchy)):
            payload = await self._get(
                "https://restapi.amap.com/v3/config/district",
                {"key": self.api_key, "keywords": adcode, "subdistrict": 0, "extensions": "base"},
                raise_unavailable=True,
            )
            resolved = list(self._district_items(payload.get("districts") or []))
            for resolved_item, resolved_parents in resolved:
                if str(resolved_item.get("adcode") or "") == adcode:
                    hierarchy = resolved_parents + (resolved_item,)
                    city_code = self._city_code(hierarchy)
                    break
        if city_code is None:
            return None
        address = await self._destination_address(item, hierarchy)
        if address is None:
            return None
        level = str(item.get("level") or "")
        kind: Literal["city", "district", "scenic_area"] = "city" if level == "city" else "district" if level == "district" else "scenic_area"
        return DestinationMatch(id=adcode, name=name.strip(), display_address=address, city_code=city_code, kind=kind)

    async def _destination_address(
        self, item: dict[str, Any], hierarchy: tuple[dict[str, Any], ...]
    ) -> str | None:
        address = self._display_address(hierarchy)
        if address is not None:
            return address
        center = item.get("center")
        if not isinstance(center, str) or "," not in center:
            return None
        payload = await self._get(
            "https://restapi.amap.com/v3/geocode/regeo",
            {"key": self.api_key, "location": center, "extensions": "base"},
            raise_unavailable=True,
        )
        component = (payload.get("regeocode") or {}).get("addressComponent")
        if not isinstance(component, dict):
            return None
        province = component.get("province")
        city = component.get("city")
        district = component.get("district")
        city_name = city if isinstance(city, str) and city.strip() else province
        values = ["中国", province, city_name, district if item.get("level") == "district" else None]
        names = [value.strip() for value in values if isinstance(value, str) and value.strip()]
        return " · ".join(dict.fromkeys(names)) if len(names) >= 3 else None

    @staticmethod
    def _district_items(items: list[Any], parents: tuple[dict[str, Any], ...] = ()) -> list[tuple[dict[str, Any], tuple[dict[str, Any], ...]]]:
        results: list[tuple[dict[str, Any], tuple[dict[str, Any], ...]]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            results.append((item, parents))
            children = item.get("districts")
            if isinstance(children, list):
                results.extend(AMapService._district_items(children, parents + (item,)))
        return results

    @staticmethod
    def _city_code(hierarchy: tuple[dict[str, Any], ...]) -> str | None:
        for item in reversed(hierarchy):
            if item.get("level") == "city":
                adcode = item.get("adcode")
                if isinstance(adcode, str) and adcode.isdigit() and len(adcode) == 6:
                    return adcode
        for item in reversed(hierarchy):
            adcode = item.get("adcode")
            if isinstance(adcode, str) and adcode.isdigit() and len(adcode) >= 6:
                return f"{adcode[:4]}00"
        return None

    @staticmethod
    def _display_address(hierarchy: tuple[dict[str, Any], ...]) -> str | None:
        names: list[str] = []
        for item in hierarchy:
            level = item.get("level")
            name = item.get("name")
            if level in {"country", "province", "city", "district"} and isinstance(name, str) and name.strip():
                if not names or names[-1] != name.strip():
                    names.append(name.strip())
        return " · ".join(names) if len(names) >= 3 else None

    @staticmethod
    def _rank_destination_matches(matches: list[DestinationMatch], query: str) -> list[DestinationMatch]:
        normalized_query = AMapService._normalize_destination_name(query)
        unique = {match.id: match for match in matches}
        return sorted(
            unique.values(),
            key=lambda match: (
                0 if AMapService._normalize_destination_name(match.name) == normalized_query else 1
                if AMapService._normalize_destination_name(match.name).startswith(normalized_query) else 2,
                match.kind != "city",
                match.name,
                match.id,
            ),
        )

    @staticmethod
    def _normalize_destination_name(value: str) -> str:
        return value.strip().removesuffix("市").removesuffix("区").removesuffix("县")

    @staticmethod
    def _poi(item: dict[str, Any]) -> MapPOI | None:
        location = item.get("location")
        if not isinstance(location, str) or "," not in location:
            return None
        try:
            longitude, latitude = (float(value) for value in location.split(",", 1))
        except ValueError:
            return None
        poi_id = item.get("id")
        name = item.get("name")
        if not isinstance(poi_id, str) or not isinstance(name, str):
            return None
        return MapPOI(
            id=poi_id,
            name=name,
            address=str(item.get("address") or item.get("formatted_address") or ""),
            location=(longitude, latitude),
            city=str(item["cityname"]) if item.get("cityname") else None,
            type_name=str(item["type"]) if item.get("type") else None,
            adcode=str(item["adcode"]) if item.get("adcode") else None,
        )

    @staticmethod
    def _route(item: dict[str, Any]) -> MapRoute | MapUnavailable:
        try:
            distance_meters = int(item["distance"])
        except (KeyError, TypeError, ValueError):
            return MapUnavailable("MAP_UNAVAILABLE", "The driving route did not include a distance.")
        duration = (item.get("cost") or {}).get("duration")
        try:
            duration_seconds = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_seconds = None
        points: list[tuple[float, float]] = []
        for step in item.get("steps") or []:
            for coordinate in str(step.get("polyline") or "").split(";"):
                try:
                    longitude, latitude = (float(value) for value in coordinate.split(",", 1))
                except ValueError:
                    continue
                if not points or points[-1] != (longitude, latitude):
                    points.append((longitude, latitude))
        return MapRoute(distance_meters, duration_seconds, tuple(points)) if len(points) > 1 else MapUnavailable(
            "MAP_UNAVAILABLE", "The driving route did not include a path."
        )


class UnavailableMapService:
    async def verify_poi(self, poi_id: str) -> MapUnavailable:
        return MapUnavailable()
