from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, max_length=64)
    avatar_asset_id: str | None = Field(default=None, max_length=36)


class ProfileResponse(BaseModel):
    id: str
    phone: str
    nickname: str | None
    avatar_asset_id: str | None


class AIEntitlementBalanceResponse(BaseModel):
    source: Literal["free", "membership"]
    itinerary_generation_remaining: int
    assistant_message_remaining: int
    period_end: datetime


class AIEntitlementsResponse(BaseModel):
    free: AIEntitlementBalanceResponse
    membership: AIEntitlementBalanceResponse | None = None


InterestTag = Literal["经典必玩", "吃吃喝喝", "小众探索", "拍照出片", "逛街购物", "citywalk", "自然风光", "文艺展览", "历史古建"]


class SettingsUpdateRequest(BaseModel):
    departure_city: str | None = Field(default=None, max_length=128)
    budget_level: Literal["economy", "balanced", "premium"] | None = None
    travel_pace: Literal["relaxed", "balanced", "packed"] | None = None
    interest_tags: list[InterestTag] | None = Field(default=None, max_length=9)
    traveler_type: Literal["solo", "couple", "friends", "family"] | None = None
    notifications_enabled: bool | None = None
    order_notifications: bool | None = None
    itinerary_notifications: bool | None = None
    community_notifications: bool | None = None
    profile_visibility: Literal["private", "collaborators"] | None = None

    @field_validator("interest_tags")
    @classmethod
    def unique_tags(cls, value: list[InterestTag] | None) -> list[InterestTag] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("interest_tags must not contain duplicates.")
        return value


class SettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    departure_city: str | None
    budget_level: Literal["economy", "balanced", "premium"]
    travel_pace: Literal["relaxed", "balanced", "packed"]
    interest_tags: list[InterestTag]
    traveler_type: Literal["solo", "couple", "friends", "family"]
    notifications_enabled: bool
    order_notifications: bool
    itinerary_notifications: bool
    community_notifications: bool
    profile_visibility: Literal["private", "collaborators"]
