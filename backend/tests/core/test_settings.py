import pytest

from app.core.settings import Settings


def test_settings_uses_distinct_amap_browser_and_server_keys() -> None:
    settings = Settings(
        app_env="test",
        mysql_dsn="mysql+pymysql://user:pass@localhost:3306/travel",
        redis_url="redis://localhost:6379/0",
        rabbitmq_url="amqp://guest:guest@localhost:5672/",
        elasticsearch_url="http://localhost:9200",
        jwt_secret="test-secret-with-at-least-32-characters",
        amap_js_api_key="browser-key",
        amap_web_service_key="server-key",
    )

    assert settings.amap_js_api_key != settings.amap_web_service_key


def test_settings_loads_minio_s3_configuration() -> None:
    settings = Settings(
        app_env="test",
        object_storage_provider="minio",
        s3_endpoint_url="http://192.168.142.50:9000",
        s3_region="us-east-1",
        s3_access_key_id="application-access-key",
        s3_secret_access_key="application-secret-key",
        s3_bucket_private="travel-private",
        s3_bucket_exports="travel-exports",
        s3_bucket_audio="travel-audio",
        s3_use_path_style=True,
    )

    assert settings.object_storage_provider == "minio"
    assert settings.s3_endpoint_url == "http://192.168.142.50:9000"
    assert settings.s3_use_path_style is True


def test_minio_storage_can_select_the_export_bucket() -> None:
    from app.integrations.object_storage import S3ObjectStorage

    settings = Settings(
        app_env="test",
        s3_endpoint_url="http://storage.test:9000",
        s3_region="us-east-1",
        s3_access_key_id="application-access-key",
        s3_secret_access_key="application-secret-key",
        s3_bucket_private="travel-private",
        s3_bucket_exports="travel-exports",
        s3_use_path_style=True,
    )

    assert S3ObjectStorage(settings, bucket=settings.s3_bucket_exports).bucket == "travel-exports"


def test_settings_rejects_non_https_magic_mcp_url() -> None:
    with pytest.raises(ValueError, match="magic_mcp_websearch_url must be an HTTPS URL"):
        Settings(app_env="test", magic_mcp_websearch_url="http://mcp.example.com/search")


def test_settings_accepts_https_magic_mcp_url() -> None:
    settings = Settings(
        app_env="test",
        magic_mcp_websearch_url="https://mcp.example.com/search",
        magic_mcp_train_url="https://mcp.example.com/train",
        magic_mcp_flight_url="https://mcp.example.com/flight",
    )

    assert settings.magic_mcp_websearch_url == "https://mcp.example.com/search"


def test_settings_rejects_non_positive_magic_mcp_timeout_when_ai_disabled() -> None:
    with pytest.raises(ValueError, match="magic_mcp_timeout_seconds must be positive"):
        Settings(app_env="test", magic_mcp_timeout_seconds=0)
