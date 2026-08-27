from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.base import validate_uuid_v4


def _normalized_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Value must not be blank.")
    return normalized


class MembershipPlanCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    duration_days: int = Field(ge=1, le=3650)
    entitlement_codes: list[str] = Field(min_length=1, max_length=100)
    price_amount: Decimal = Field(gt=Decimal("0.00"), max_digits=10, decimal_places=2)
    currency: Literal["CNY"]
    generation_quota: int = Field(ge=0, le=10_000)
    assistant_quota: int = Field(ge=0, le=1_000_000)
    purchasable: Literal[False] = False

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return _normalized_text(value).lower()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalized_text(value)

    @field_validator("entitlement_codes")
    @classmethod
    def normalize_entitlements(cls, values: list[str]) -> list[str]:
        normalized = [_normalized_text(value).lower() for value in values]
        if any(len(value) > 64 for value in normalized):
            raise ValueError("Entitlement codes must be at most 64 characters.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Entitlement codes must be unique.")
        return normalized


class MembershipPlanUpdate(BaseModel):
    price_amount: Decimal | None = Field(default=None, gt=Decimal("0.00"), max_digits=10, decimal_places=2)
    currency: Literal["CNY"] | None = None
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    generation_quota: int | None = Field(default=None, ge=0, le=10_000)
    assistant_quota: int | None = Field(default=None, ge=0, le=1_000_000)
    purchasable: bool | None = None


class MembershipPlanResponse(BaseModel):
    id: str
    code: str
    name: str
    duration_days: int
    entitlement_codes: list[str]
    status: Literal["draft", "published", "archived"]
    price_amount: Decimal
    currency: Literal["CNY"]
    generation_quota: int
    assistant_quota: int
    purchasable: bool
    created_at: datetime
    updated_at: datetime


class MembershipPlanPage(BaseModel):
    items: list[MembershipPlanResponse]
    next_cursor: None = None


class MembershipGrantCreate(BaseModel):
    user_id: str = Field(min_length=36, max_length=36)
    plan_id: str = Field(min_length=36, max_length=36)
    valid_from: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("user_id", "plan_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_uuid_v4(value, "identifier")

    @field_validator("valid_from")
    @classmethod
    def normalize_valid_from(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("valid_from must include a timezone.")
        return value.astimezone(UTC)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return _normalized_text(value)


class MembershipRevokeCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return _normalized_text(value)


class MembershipResponse(BaseModel):
    id: str
    plan_id: str
    plan_code: str
    plan_name: str
    status: Literal["active", "revoked", "expired"]
    valid_from: datetime
    valid_until: datetime
    entitlement_codes: list[str]


class AdminMembershipResponse(MembershipResponse):
    user_id: str
    grant_source: Literal["admin_grant"]
    granted_by: str
    revoked_by: str | None
    revoked_at: datetime | None
    revoke_reason: str | None


class EntitlementResponse(BaseModel):
    id: str
    membership_id: str
    code: str
    valid_from: datetime
    valid_until: datetime
    status: Literal["active"] = "active"
