from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError


class ChecklistCreateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=500)


class ChecklistUpdateRequest(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=64)
    content: str | None = Field(default=None, min_length=1, max_length=500)
    checked: bool | None = None


class ChecklistItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    content: str
    checked: bool
    source: str


class ChecklistListResponse(BaseModel):
    items: list[ChecklistItemResponse]


class BudgetCreateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        currency = value.upper()
        if currency not in {"CNY", "USD", "EUR", "GBP", "JPY", "KRW", "HKD", "TWD", "THB", "SGD", "AUD", "CAD", "NZD", "CHF", "AED"}:
            raise PydanticCustomError("currency_invalid", "currency must be a supported ISO 4217 code.")
        return currency


class BudgetUpdateRequest(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=64)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    description: str | None = Field(default=None, max_length=2000)


class BudgetItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    amount: Decimal
    currency: str
    description: str | None


class BudgetTotalResponse(BaseModel):
    currency: str
    total_amount: Decimal


class BudgetListResponse(BaseModel):
    items: list[BudgetItemResponse]
    totals: list[BudgetTotalResponse]
