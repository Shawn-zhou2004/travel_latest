from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.workers.main import main, validate_worker_configuration


def test_worker_check_config_exits_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "MYSQL_DSN", "mysql+pymysql://travel_app:password@localhost:3306/ai_travel_platform"
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://admin:password@localhost:5672/")
    monkeypatch.setenv("ELASTICSEARCH_URL", "http://localhost:9200")
    monkeypatch.setenv("JWT_SECRET", "a" * 64)
    assert main(["--check-config"]) == 0


def test_worker_configuration_accepts_runtime_urls() -> None:
    settings = Settings(
        app_env="test",
        mysql_dsn="mysql+pymysql://travel_app:password@localhost:3306/ai_travel_platform",
        redis_url="redis://localhost:6379/0",
        rabbitmq_url="amqp://admin:password@localhost:5672/",
        elasticsearch_url="http://localhost:9200",
        jwt_secret="a" * 64,
    )
    validate_worker_configuration(settings)
