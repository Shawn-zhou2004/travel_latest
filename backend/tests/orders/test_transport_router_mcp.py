import asyncio
from datetime import date

import pytest

from app.integrations.mcp.transport import MagicFlightOfferProvider, MagicTrainOfferProvider
from app.integrations.suppliers.client import SupplierSearchRequest, UnavailableSupplierAdapter
from app.modules.orders import router
from app.modules.orders.schemas import SearchJobCreate


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> type:
    class FakeSettings:
        magic_mcp_train_url = "https://train.example.test/mcp"
        magic_mcp_train_tool = "search_trains"
        magic_mcp_flight_url = "https://flight.example.test/mcp"
        magic_mcp_flight_tool = "search_flights"
        magic_mcp_api_key = "transport-secret"
        magic_mcp_timeout_seconds = 15

    monkeypatch.setattr("app.core.settings.Settings", FakeSettings)
    return FakeSettings


def _search(search_type: str) -> SearchJobCreate:
    return SearchJobCreate(
        search_type=search_type,
        origin="Hangzhou",
        destination="Shanghai",
        depart_date=date(2026, 10, 1),
        passenger_count=1,
    )


def test_train_uses_magic_mcp_when_train_configuration_is_complete(settings: type) -> None:
    adapter = router.get_supplier_adapter(_search("train"))

    assert isinstance(adapter, router._TransportSupplierAdapter)
    assert isinstance(adapter._provider, MagicTrainOfferProvider)


def test_flight_uses_magic_mcp_when_flight_configuration_is_complete(settings: type) -> None:
    adapter = router.get_supplier_adapter(_search("flight"))

    assert isinstance(adapter, router._TransportSupplierAdapter)
    assert isinstance(adapter._provider, MagicFlightOfferProvider)


@pytest.mark.parametrize("search_type", ["train", "flight", "hotel", "ride"])
def test_incomplete_or_unsupported_transport_configuration_is_unavailable(settings: type, search_type: str) -> None:
    if search_type == "train":
        settings.magic_mcp_train_tool = None
    elif search_type == "flight":
        settings.magic_mcp_flight_url = None

    assert isinstance(router.get_supplier_adapter(_search(search_type)), UnavailableSupplierAdapter)


def test_transport_adapter_sends_only_search_fields_and_never_exposes_configuration_secrets(settings: type, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Provider:
        async def search(self, request: object) -> object:
            captured.update(vars(request))
            from app.integrations.mcp.transport import TransportOfferResult

            return TransportOfferResult(True, "OK", "ok")

    monkeypatch.setattr(router, "MagicTrainOfferProvider", lambda config: Provider())
    adapter = router.get_supplier_adapter(_search("train"))

    result = asyncio.run(
        adapter.search(
            SupplierSearchRequest(
                search_type="flight",
                origin="Hangzhou",
                destination="Shanghai",
                depart_date=date(2026, 10, 1),
                passenger_count=1,
            )
        )
    )
    assert result.available
    assert captured.keys() == {"origin", "destination", "depart_date", "passenger_count"}
    assert "transport-secret" not in repr(adapter)
