from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_generates_a_valid_request_id() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "ai-travel-api"
    assert UUID(response.headers["x-request-id"])


def test_health_preserves_a_valid_supplied_request_id() -> None:
    client = TestClient(create_app())
    request_id = "0c3c55fe-0b37-4ef8-8ecc-585b2b9a1d50"

    response = client.get("/api/v1/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id


@pytest.mark.parametrize("request_id", ["", "not-a-uuid"])
def test_health_replaces_blank_or_invalid_supplied_request_id(request_id: str) -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert UUID(response.headers["x-request-id"])
    assert response.headers["x-request-id"] != request_id


def test_unknown_route_returns_error_envelope() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/missing")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "Resource not found.",
        "request_id": response.headers["x-request-id"],
        "details": {},
    }


def test_payment_query_route_requires_authentication() -> None:
    client = TestClient(create_app())

    response = client.post("/api/v1/travel-orders/order-1:query-payment")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_configured_consumer_origin_can_preflight_payment_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://consumer.example.test")
    client = TestClient(create_app())

    response = client.options(
        "/api/v1/travel-orders/order-1/payments",
        headers={
            "Origin": "https://consumer.example.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://consumer.example.test"
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()
