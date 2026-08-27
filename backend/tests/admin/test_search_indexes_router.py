import asyncio

from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app
from app.modules.admin.search_indexes import SearchIndexInventoryService
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore


def _token(roles: list[str]) -> tuple[object, str]:
    auth = AuthService(InMemoryTTLStore())
    return auth, auth.create_access_token(user_id="admin-1", audience="admin", roles=roles, session_id="session-1")


def test_search_index_inventory_requires_platform_admin(monkeypatch):
    auth, token = _token(["provider_admin"])
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/search-indexes", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_search_index_inventory_response_shape_and_configured_order(monkeypatch):
    auth, token = _token(["platform_admin"])
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    monkeypatch.setattr("app.modules.admin.router.Settings", lambda: Settings(app_env="test", elasticsearch_url=None))
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/search-indexes", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["logical_name"] for item in items] == ["travel_knowledge", "official_knowledge", "community_knowledge", "user_memory"]
    assert [item["index_name"] for item in items] == ["travel_knowledge_v1", "travel_official_knowledge_v1", "travel_community_knowledge_v1", "user_memory_v1"]
    assert set(items[0]) == {"logical_name", "index_name", "status", "document_count", "message"}
    assert all(item["status"] == "unavailable" for item in items)


def test_search_index_inventory_keeps_external_failures_at_item_level():
    class Indices:
        async def exists(self, *, index: str) -> bool:
            if index == "broken":
                raise RuntimeError("probe failed")
            return True

    class Client:
        indices = Indices()

        async def info(self):
            return {}

        async def count(self, *, index: str):
            return {"count": 3}

        async def close(self):
            return None

    settings = Settings(app_env="test", elasticsearch_url="http://elastic", elasticsearch_index_official_knowledge="broken")
    items = asyncio.run(SearchIndexInventoryService(settings, lambda _: Client()).inventory())
    assert items[0]["status"] == "healthy"
    assert items[1]["status"] == "degraded"
    assert all(item["index_name"] != "arbitrary" for item in items)
