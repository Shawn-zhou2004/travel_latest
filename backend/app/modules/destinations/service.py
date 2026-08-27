from app.modules.destinations.schemas import DestinationResponse
from app.modules.maps.service import AMapService, DestinationSearchUnavailable


class DestinationService:
    def __init__(self, maps: AMapService) -> None:
        self._maps = maps

    async def search(self, query: str) -> list[DestinationResponse]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("A destination query is required.")
        matches = await self._maps.search_destinations(normalized_query)
        return [DestinationResponse(**match.__dict__) for match in matches]
