import asyncio
from datetime import date

from app.integrations.suppliers import (
    SupplierFulfillmentConfirmationRequest,
    UnavailableSupplierAdapter,
)
from app.integrations.suppliers.client import SupplierSearchRequest


def test_unavailable_supplier_explicitly_rejects_fulfillment_confirmation() -> None:
    request = SupplierFulfillmentConfirmationRequest(
        source="authorized_supplier",
        external_offer_id="offer-123",
        order_reference="TO202608070001",
        idempotency_key="fulfillment-confirmation-1",
    )

    result = asyncio.run(UnavailableSupplierAdapter().confirm_fulfillment(request))

    assert result.confirmed is False
    assert result.code == "SUPPLIER_UNAVAILABLE"
    assert result.supplier_confirmation_id is None
    assert result.message == "No authorized supplier integration is configured for fulfillment confirmation."


def test_unavailable_supplier_search_behavior_is_unchanged() -> None:
    request = SupplierSearchRequest(
        search_type="hotel",
        origin="Hangzhou",
        destination="Shanghai",
        depart_date=date(2026, 10, 1),
        passenger_count=1,
    )

    result = asyncio.run(UnavailableSupplierAdapter().search(request))

    assert result.available is False
    assert result.code == "SUPPLIER_UNAVAILABLE"
    assert result.offers == ()
    assert result.message == "No authorized supplier integration is configured for travel search."
