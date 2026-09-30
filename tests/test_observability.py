from pathlib import Path

from fastapi.testclient import TestClient

from enterprise_rag.core.readiness import ReadinessService
from enterprise_rag.observability.metrics import MetricsRegistry


def test_metrics_slo_and_real_readiness(client: TestClient) -> None:
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["components"] == {
        "model_provider": "configured:mock",
        "database": "ready",
    }

    upload = client.post(
        "/api/v1/knowledge/documents/ingest",
        files={
            "file": (
                "range.md",
                "# 续航\n\n星海 S7 的 CLTC 续航里程是 650 公里。".encode(),
                "text/markdown",
            )
        },
        data={"source_uri": "kb://vehicle/range"},
    )
    assert upload.status_code == 200
    answer = client.post(
        "/api/v1/rag/answer",
        json={"query": "星海 S7 的 CLTC 续航是多少"},
    )
    assert answer.status_code == 200
    assert answer.json()["status"] == "answered"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert "enterprise_rag_http_requests_total" in metrics.text
    assert 'route="/api/v1/rag/answer"' in metrics.text
    assert 'enterprise_rag_answers_total{status="answered",repaired="false"} 1' in metrics.text
    assert 'enterprise_rag_retrieval_routes_total{route="semantic"' in metrics.text

    slo = client.get("/api/v1/observability/slo")
    assert slo.status_code == 200
    body = slo.json()
    assert body["status"] == "healthy"
    assert body["request_samples"] >= 4
    assert body["answer_samples"] == 1
    assert all(check["passed"] is True for check in body["checks"])


def test_slo_reports_no_data_and_violations() -> None:
    registry = MetricsRegistry()
    empty = registry.slo_snapshot(
        availability_target=0.99,
        p95_latency_ms_target=100,
        answer_success_target=0.90,
    )
    assert empty.status == "no_data"

    registry.record_http("GET", "/broken", 500, 0.5)
    registry.record_answer("needs_human", True, 0.5)
    violated = registry.slo_snapshot(
        availability_target=0.99,
        p95_latency_ms_target=100,
        answer_success_target=0.90,
    )
    assert violated.status == "violated"
    assert all(check.passed is False for check in violated.checks)


def test_readiness_detects_invalid_database_target() -> None:
    readiness = ReadinessService(Path("work"), "mock").check()

    assert readiness.ready is False
    assert readiness.components["database"].startswith("error:")
