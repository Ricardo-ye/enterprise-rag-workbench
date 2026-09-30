from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from enterprise_rag.core.config import Settings
from enterprise_rag.main import create_app


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "model_provider": "mock",
        "log_level": "ERROR",
        "database_path": Path("work/test-databases") / f"security-{uuid4().hex}.db",
        "embedding_dimensions": 128,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_api_key_protects_non_health_endpoints() -> None:
    settings = _settings(api_key=SecretStr("test-secret-key-123"))
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/ui").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        unauthorized = client.post(
            "/api/v1/system/model/check",
            json={"prompt": "hello"},
        )
        authorized = client.post(
            "/api/v1/system/model/check",
            json={"prompt": "hello"},
            headers={"X-API-Key": "test-secret-key-123"},
        )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"
    assert authorized.status_code == 200


def test_rate_limit_returns_retry_after() -> None:
    settings = _settings(rate_limit_requests_per_minute=1)
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/v1/system/model/check", json={"prompt": "one"})
        second = client.post("/api/v1/system/model/check", json={"prompt": "two"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


def test_production_requires_key_and_explicit_hosts() -> None:
    with pytest.raises(ValidationError, match="RAG_API_KEY"):
        _settings(environment="production", api_key=None)

    with pytest.raises(ValidationError, match="RAG_TRUSTED_HOSTS"):
        _settings(
            environment="production",
            api_key=SecretStr("production-key-1234"),
            trusted_hosts="*",
        )

    with pytest.raises(ValidationError, match="RAG_DATABASE_PATH must be absolute"):
        _settings(
            environment="production",
            api_key=SecretStr("production-key-1234"),
            trusted_hosts="rag.example.com",
        )
