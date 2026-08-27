from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.modules.auth.dependencies import CurrentConsumer
from app.modules.destinations.schemas import DestinationSearchResponse
from app.modules.destinations.service import DestinationService
from app.modules.maps.service import AMapService, DestinationSearchUnavailable

router = APIRouter(prefix="/destinations", tags=["destinations"])


def get_destination_service() -> DestinationService:
    return DestinationService(AMapService())


Service = Annotated[DestinationService, Depends(get_destination_service)]


@router.get("", response_model=DestinationSearchResponse)
async def search_destinations(
    claims: CurrentConsumer,
    service: Service,
    query: Annotated[str, Query(min_length=1, max_length=80)],
) -> DestinationSearchResponse:
    del claims
    if not query.strip():
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "A destination query is required."})
    try:
        return DestinationSearchResponse(items=await service.search(query))
    except ValueError as error:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(error)}) from error
    except DestinationSearchUnavailable as error:
        raise HTTPException(
            503,
            detail={"code": "DESTINATION_SEARCH_UNAVAILABLE", "message": "Destination search is unavailable."},
        ) from error
