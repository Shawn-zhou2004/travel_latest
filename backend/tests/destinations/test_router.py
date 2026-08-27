from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.destinations.router import get_destination_service
from app.modules.destinations.schemas import DestinationResponse
from app.modules.maps.service import DestinationSearchUnavailable


class StubDestinationService:
    async def search(self, query: str) -> list[DestinationResponse]:
        assert query == "长沙"
        return [DestinationResponse(
            id="430100",
            name="长沙市",
            display_address="中国 · 湖南省 · 长沙市",
            city_code="430100",
            kind="city",
        )]


def test_destination_search_requires_consumer_auth() -> None:
    app = create_app()
    app.dependency_overrides[get_destination_service] = StubDestinationService
    with TestClient(app) as client:
        response = client.get("/api/v1/destinations", params={"query": "长沙"})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_destination_search_returns_public_normalized_results() -> None:
    auth = AuthService(InMemoryTTLStore())
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_destination_service] = StubDestinationService
    headers = {"Authorization": f"Bearer {auth.create_access_token(user_id='consumer-1', audience='consumer', roles=['user'])}"}
    with TestClient(app) as client:
        response = client.get("/api/v1/destinations", params={"query": "长沙"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["items"] == [{
        "id": "430100",
        "name": "长沙市",
        "display_address": "中国 · 湖南省 · 长沙市",
        "city_code": "430100",
        "kind": "city",
    }]


def test_destination_search_rejects_whitespace_query_after_trimming() -> None:
    auth = AuthService(InMemoryTTLStore())
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_destination_service] = StubDestinationService
    headers = {"Authorization": f"Bearer {auth.create_access_token(user_id='consumer-1', audience='consumer', roles=['user'])}"}
    with TestClient(app) as client:
        response = client.get("/api/v1/destinations", params={"query": "   "}, headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_destination_search_returns_unavailable_error() -> None:
    class UnavailableService:
        async def search(self, query: str) -> list[DestinationResponse]:
            raise DestinationSearchUnavailable()

    auth = AuthService(InMemoryTTLStore())
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_destination_service] = UnavailableService
    headers = {"Authorization": f"Bearer {auth.create_access_token(user_id='consumer-1', audience='consumer', roles=['user'])}"}
    with TestClient(app) as client:
        response = client.get("/api/v1/destinations", params={"query": "长沙"}, headers=headers)
    assert response.status_code == 503
    assert response.json()["code"] == "DESTINATION_SEARCH_UNAVAILABLE"


def test_destination_search_returns_empty_items_for_valid_query_without_matches() -> None:
    class EmptyService:
        async def search(self, query: str) -> list[DestinationResponse]:
            assert query == "不存在的地方"
            return []

    auth = AuthService(InMemoryTTLStore())
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_destination_service] = EmptyService
    headers = {"Authorization": f"Bearer {auth.create_access_token(user_id='consumer-1', audience='consumer', roles=['user'])}"}
    with TestClient(app) as client:
        response = client.get("/api/v1/destinations", params={"query": "不存在的地方"}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}
