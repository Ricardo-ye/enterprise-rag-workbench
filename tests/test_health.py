from fastapi.testclient import TestClient


def test_live_probe(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "test-request-1"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "enterprise-rag",
        "version": "0.1.0",
        "environment": "test",
        "model_provider": None,
    }
    assert response.headers["X-Request-ID"] == "test-request-1"
    assert float(response.headers["X-Process-Time-Ms"]) >= 0


def test_ready_probe_exposes_provider(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["model_provider"] == "mock"
