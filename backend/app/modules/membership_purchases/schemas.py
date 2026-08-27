from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import validate_uuid_v4


class MembershipPurchaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_plan_id: str = Field(min_length=36, max_length=36)

    @field_validator("membership_plan_id")
    @classmethod
    def validate_plan_id(cls, value: str) -> str:
        return validate_uuid_v4(value, "membership_plan_id")


class MembershipPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["alipay_sandbox"]


class MembershipPurchaseResponse(BaseModel):
    id: str
    membership_plan_id: str
    plan_name: str
    amount: Decimal
    currency: str
    duration_days: int
    generation_quota: int
    assistant_quota: int
    status: str
    payment_status: str
    authorization_status: str
    payment_no: str | None
    paid_at: datetime | None
    authorized_at: datetime | None
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime


class MembershipPaymentResponse(BaseModel):
    payment_no: str
    amount: Decimal
    currency: str
    status: str
    redirect_url: str


class MembershipQrPaymentResponse(BaseModel):
    attempt_id: str | None
    payment_no: str | None
    qr_code: str | None
    expires_at: datetime | None
    status: str | None
    payment_status: str
    authorization_status: str


class MembershipPurchasePage(BaseModel):
    items: list[MembershipPurchaseResponse]


class AdminMembershipPurchaseResponse(BaseModel):
    id: str
    user_id: str
    membership_plan_id: str
    plan_name: str
    amount: Decimal
    currency: str
    duration_days: int
    generation_quota: int
    assistant_quota: int
    status: str
    payment_status: str
    authorization_status: str
    failure_code: str | None
    paid_at: datetime | None
    authorized_at: datetime | None
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime


class AdminMembershipPurchasePage(BaseModel):
    items: list[AdminMembershipPurchaseResponse]
