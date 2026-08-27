from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol


SearchType = Literal["flight", "hotel", "ride"]


@dataclass(frozen=True)
class SupplierSearchRequest:
    search_type: SearchType
    origin: str
    destination: str
    depart_date: date
    passenger_count: int


@dataclass(frozen=True)
class SupplierOffer:
    source: str
    external_offer_id: str
    title: str
    amount: str
    currency: str
    valid_until: datetime
    availability: str
    change_rules: dict[str, object]
    snapshot: dict[str, object]


@dataclass(frozen=True)
class SupplierSearchResult:
    available: bool
    code: str
    message: str
    offers: tuple[SupplierOffer, ...] = ()


@dataclass(frozen=True)
class SupplierFulfillmentConfirmationRequest:
    """Supplier inputs reconstructed from the immutable selected-offer record."""

    source: str
    external_offer_id: str
    order_reference: str
    idempotency_key: str


@dataclass(frozen=True)
class SupplierFulfillmentConfirmationResult:
    confirmed: bool
    code: str
    message: str
    supplier_confirmation_id: str | None = None


class SupplierAdapter(Protocol):
    async def search(self, request: SupplierSearchRequest) -> SupplierSearchResult: ...

    async def confirm_fulfillment(
        self,
        request: SupplierFulfillmentConfirmationRequest,
    ) -> SupplierFulfillmentConfirmationResult: ...


class UnavailableSupplierAdapter:
    """Safe default until an authorized supplier integration is configured."""

    async def search(self, request: SupplierSearchRequest) -> SupplierSearchResult:
        return SupplierSearchResult(
            available=False,
            code="SUPPLIER_UNAVAILABLE",
            message="No authorized supplier integration is configured for travel search.",
        )

    async def confirm_fulfillment(
        self,
        request: SupplierFulfillmentConfirmationRequest,
    ) -> SupplierFulfillmentConfirmationResult:
        return SupplierFulfillmentConfirmationResult(
            confirmed=False,
            code="SUPPLIER_UNAVAILABLE",
            message="No authorized supplier integration is configured for fulfillment confirmation.",
        )
