from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app


def test_client_config_returns_browser_map_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.maps.router.Settings",
        lambda: Settings(app_env="development", amap_js_api_key="browser-key", amap_security_js_code="security-code"),
    )

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/map/client-config")

    assert response.status_code == 200
    assert response.json() == {"js_api_key": "browser-key", "service_host": "/api/v1/map/amap-service"}
