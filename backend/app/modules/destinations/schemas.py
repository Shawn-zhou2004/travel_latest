from typing import Literal

from pydantic import BaseModel


class DestinationResponse(BaseModel):
    id: str
    name: str
    display_address: str
    city_code: str
    kind: Literal["city", "district", "scenic_area"]


class DestinationSearchResponse(BaseModel):
    items: list[DestinationResponse]
