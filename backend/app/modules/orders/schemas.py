from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class SearchJobCreate(BaseModel):
    search_type: Literal["train", "flight", "hotel", "ride"]
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    depart_date: date
    passenger_count: int = Field(ge=1, le=9)


class OfferResponse(BaseModel):
    id: str
    source: str
    title: str
    amount: Decimal
    currency: str
    availability: str
    valid_until: datetime
    retrieved_at: datetime
    change_rules: dict[str, object]


class SearchJobResponse(BaseModel):
    id: str
    status: str
    source: str
    unavailable_code: str | None
    retrieved_at: datetime
    offers: list[OfferResponse] = Field(default_factory=list)


class PassengerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    document_type: Literal["identity_card", "passport"]
    document_number: str = Field(min_length=4, max_length=64)
    seat_preference: Literal["window", "aisle", "none"] = "none"


class OrderCreate(BaseModel):
    offer_id: str
    passengers: list[PassengerCreate] = Field(default_factory=list, max_length=9)


class PaymentCreate(BaseModel):
    provider: Literal["alipay_sandbox"]


class OrderResponse(BaseModel):
    id: str
    order_no: str
    amount: Decimal
    currency: str
    status: str
    payment_status: str
    fulfillment_status: str
    failure_code: str | None = None
    created_at: datetime


class MockTicketResponse(BaseModel):
    id: str
    transport_type: str
    status: str
    mock_ticket_no: str | None
    seat_assignments: dict[str, object]
    passenger_facts: dict[str, object]
    failure_code: str | None


class PaymentResponse(BaseModel):
    id: str
    payment_no: str
    amount: Decimal
    currency: str
    status: str
    redirect_url: str


class RefundCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: Literal["CNY"]
    reason: str = Field(min_length=1, max_length=500)


class RefundResponse(BaseModel):
    id: str
    status: str
    amount: Decimal
    currency: str
