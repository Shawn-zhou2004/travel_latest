from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderApplicationCreate(BaseModel):
    provider_type: str = Field(min_length=1, max_length=32)
    legal_name: str = Field(min_length=1, max_length=160)
    contact: str = Field(min_length=1, max_length=160)
    qualification_asset_ids: list[str] = Field(min_length=1)
    claimed_poi_ids: list[str] = Field(default_factory=list)


class ProviderDecision(BaseModel):
    status: Literal["approved", "rejected"]
    review_reason: str = Field(min_length=1, max_length=500)


class ExperienceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    poi_id: str = Field(min_length=1, max_length=128)
    price_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    cancellation_policy: str = Field(min_length=1)
    status: Literal["draft", "published"] = "draft"


class SessionCreate(BaseModel):
    starts_at: datetime
    capacity: int = Field(gt=0, le=1000)
    price_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class ExperienceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1)
    price_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    cancellation_policy: str | None = Field(default=None, min_length=1)
    status: Literal["draft", "published", "archived"] | None = None


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime | None = None
    capacity: int | None = Field(default=None, gt=0, le=1000)
    status: Literal["scheduled", "cancelled", "completed"] | None = None
    price_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class BookingCreate(BaseModel):
    experience_session_id: str
    traveler_count: int = Field(gt=0, le=20)


class VerifyBooking(BaseModel):
    verification_code: str = Field(min_length=6, max_length=24)


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str = Field(min_length=1, max_length=2000)


class PublicProvider(BaseModel):
    id: str
    name: str


class VerifiedPoi(BaseModel):
    id: str
    name: str
    address: str


class PublicExperienceSession(BaseModel):
    id: str
    starts_at: datetime
    price_amount: Decimal
    currency: str
    remaining_capacity: int
    status: Literal["scheduled"]


class PublicExperience(BaseModel):
    id: str
    title: str
    poi: VerifiedPoi
    provider: PublicProvider
    price_amount: Decimal
    currency: str
    status: Literal["published"]


class PublicExperienceDetail(PublicExperience):
    description: str
    cancellation_policy: str
    sessions: list[PublicExperienceSession]


class PublicExperiencePage(BaseModel):
    items: list[PublicExperience]


class ProviderExperience(BaseModel):
    id: str
    provider_id: str
    title: str
    description: str
    poi: VerifiedPoi
    price_amount: Decimal
    currency: str
    cancellation_policy: str
    status: Literal["draft", "published", "archived"]


class ProviderExperiencePage(BaseModel):
    items: list[ProviderExperience]


class ProviderExperienceSession(BaseModel):
    id: str
    experience_id: str
    starts_at: datetime
    capacity: int
    reserved_count: int
    remaining_capacity: int
    price_amount: Decimal | None
    currency: str | None
    status: Literal["scheduled", "cancelled", "completed"]


class ProviderExperienceSessionPage(BaseModel):
    items: list[ProviderExperienceSession]


class ProviderExperienceBooking(BaseModel):
    id: str
    experience_title: str
    starts_at: datetime
    traveler_count: int
    status: Literal["reserved", "verified", "cancelled"]
    verified_at: datetime | None


class ProviderExperienceBookingPage(BaseModel):
    items: list[ProviderExperienceBooking]


class ExperienceCreated(BaseModel):
    id: str
    status: Literal["draft", "published", "archived"]


class SessionCreated(BaseModel):
    id: str
    status: Literal["scheduled", "cancelled", "completed"]
    remaining_capacity: int
