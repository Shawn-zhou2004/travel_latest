from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.responses import Response

from app.core.settings import Settings
from app.modules.auth.dependencies import CurrentConsumer
from app.modules.maps.service import AMapService, MapPOI

router = APIRouter(prefix="/map", tags=["maps"])


class POIResponse(BaseModel):
    id: str
    name: str
    address: str
    longitude: float
    latitude: float
    city: str | None = None
    type_name: str | None = None

    @classmethod
    def from_poi(cls, poi: MapPOI) -> "POIResponse":
        return cls(
            id=poi.id,
            name=poi.name,
            address=poi.address,
            longitude=poi.location[0],
            latitude=poi.location[1],
            city=poi.city,
            type_name=poi.type_name,
        )


class MapClientConfigResponse(BaseModel):
    js_api_key: str | None = None
    service_host: str


def get_map_service() -> AMapService:
    return AMapService()


Service = Annotated[AMapService, Depends(get_map_service)]


@router.get("/client-config", response_model=MapClientConfigResponse)
async def get_client_config() -> MapClientConfigResponse:
    settings = Settings()
    return MapClientConfigResponse(
        js_api_key=settings.amap_js_api_key,
        service_host="/api/v1/map/amap-service" if settings.app_env == "development" else "/_AMapService",
    )


@router.api_route("/amap-service/{service_path:path}", methods=["GET", "POST"], include_in_schema=False)
async def proxy_jsapi_service(service_path: str, request: Request, service: Service) -> Response:
    if Settings().app_env != "development":
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found."})
    status_code, content, content_type = await service.proxy_jsapi_request(
        service_path,
        method=request.method,
        params=dict(request.query_params),
        content=await request.body(),
    )
    return Response(content=content, status_code=status_code, media_type=content_type.split(";", 1)[0])


@router.get("/pois", response_model=list[POIResponse])
async def search_pois(
    claims: CurrentConsumer,
    service: Service,
    keywords: str = Query(min_length=1, max_length=100),
    city: str | None = Query(default=None, max_length=100),
) -> list[POIResponse]:
    del claims
    return [POIResponse.from_poi(poi) for poi in await service.search_pois(keywords, city)]
