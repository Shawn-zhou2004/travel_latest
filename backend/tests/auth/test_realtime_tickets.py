from fastapi.testclient import TestClient

from app.modules.auth.router import get_auth_service


def test_realtime_ticket_is_single_use_and_resource_bound(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    token = service.create_access_token(user_id="user-1", audience="consumer", roles=["user"])
    response = client.post(
        "/api/v1/realtime-tickets",
        json={"resource_type": "itinerary", "resource_id": "11111111-1111-1111-1111-111111111111"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert response.json()["expires_in"] == 60
    ticket = response.json()["ticket"]

    assert service.consume_realtime_ticket(ticket, "user-1", "itinerary", "11111111-1111-1111-1111-111111111111")
    assert not service.consume_realtime_ticket(ticket, "user-1", "itinerary", "11111111-1111-1111-1111-111111111111")
