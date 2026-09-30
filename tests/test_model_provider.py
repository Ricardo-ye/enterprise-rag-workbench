import pytest
from fastapi.testclient import TestClient

from enterprise_rag.core.config import Settings
from enterprise_rag.core.errors import ConfigurationError
from enterprise_rag.providers.factory import create_model_provider


def test_mock_model_check(client: TestClient) -> None:
    response = client.post("/api/v1/system/model/check", json={"prompt": "hello"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "provider": "mock",
        "model": "deterministic-mock-v1",
        "response": "[mock] hello",
    }


def test_openai_provider_requires_api_key() -> None:
    settings = Settings(
        environment="test",
        model_provider="openai",
        openai_api_key=None,
    )

    with pytest.raises(ConfigurationError, match="RAG_OPENAI_API_KEY"):
        create_model_provider(settings)


def test_model_check_validates_empty_prompt(client: TestClient) -> None:
    response = client.post("/api/v1/system/model/check", json={"prompt": ""})

    assert response.status_code == 422
