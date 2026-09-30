import json
from time import sleep
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from enterprise_rag.rag.circuit import CircuitBreaker, CircuitOpenError, CircuitState
from enterprise_rag.rag.fusion import reciprocal_rank_fusion
from enterprise_rag.rag.models import RetrievalHit, RetrievalRoute


def _upload(client: TestClient) -> str:
    response = client.post(
        "/api/v1/knowledge/documents/ingest",
        files={
            "file": (
                "range.md",
                "# 续航资料\n\n星海 S7 的 CLTC 续航里程是 650 公里。".encode(),
                "text/markdown",
            )
        },
        data={
            "source_uri": "kb://vehicle/range",
            "metadata_json": json.dumps({"department": "product"}),
        },
    )
    assert response.status_code == 200, response.text
    body = cast(dict[str, Any], response.json())
    return str(body["document"]["id"])


def _seed_structured_knowledge(client: TestClient) -> None:
    faq = client.post(
        "/api/v1/knowledge/faqs/import",
        json={
            "items": [
                {
                    "question": "星海 S7 的续航是多少?",
                    "answer": "CLTC 续航为 650 公里。",
                    "approved": True,
                }
            ]
        },
    )
    assert faq.status_code == 200, faq.text
    kg = client.post(
        "/api/v1/kbqa/kg/triples/import",
        json={
            "triples": [
                {
                    "subject": "星海 S7",
                    "predicate": "CLTC 续航",
                    "object": "650 公里",
                    "subject_aliases": ["S7"],
                    "predicate_aliases": ["续航"],
                }
            ]
        },
    )
    assert kg.status_code == 200, kg.text


def test_five_route_retrieval_fuses_deduplicates_and_cites(client: TestClient) -> None:
    document_id = _upload(client)
    _seed_structured_knowledge(client)

    response = client.post(
        "/api/v1/rag/retrieve",
        json={"query": "星海 S7 的 CLTC 续航里程是多少"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [route["route"] for route in body["routes"]] == [
        "semantic",
        "lexical",
        "web",
        "kg",
        "faq",
    ]
    assert next(route for route in body["routes"] if route["route"] == "web")["status"] == "skipped"
    assert any(hit["source_id"] == document_id for hit in body["hits"])
    assert any(hit["source_type"] == "kg" for hit in body["hits"])
    assert any(hit["source_type"] == "faq" for hit in body["hits"])
    document_hit = next(hit for hit in body["hits"] if hit["source_id"] == document_id)
    assert set(document_hit["retrieval_routes"]) == {"semantic", "lexical"}
    assert [citation["index"] for citation in body["citations"]] == list(
        range(1, len(body["citations"]) + 1)
    )
    assert "[1]" in body["context"]
    assert "Source:" in body["context"]


def test_retrieval_evaluation_reports_standard_metrics(client: TestClient) -> None:
    document_id = _upload(client)
    response = client.post(
        "/api/v1/rag/evaluate",
        json={
            "k": 3,
            "cases": [
                {
                    "query": "星海 S7 CLTC 续航里程",
                    "relevant_source_ids": [document_id],
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["case_count"] == 1
    assert body["recall_at_k"] == 1.0
    assert body["mrr"] > 0
    assert body["ndcg_at_k"] > 0


def test_assistant_rag_path_returns_grounded_answer(client: TestClient) -> None:
    _upload(client)
    response = client.post(
        "/api/v1/assistant/respond",
        json={"query": "请介绍星海 S7 的 CLTC 续航里程"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "answered"
    assert body["retrieval"]["hits"]
    assert body["generation"]["used_citation_indices"]
    assert body["metadata"]["quality_record_id"]


def test_rrf_merges_same_chunk_and_keeps_multiple_document_chunks() -> None:
    def hit(route: RetrievalRoute, hit_id: str, content: str) -> RetrievalHit:
        return RetrievalHit(
            id=hit_id,
            route=route,
            source_type="document",
            source_id="document-1",
            content=content,
            score=0.8,
            title="Manual",
            source_uri="kb://manual",
        )

    fused = reciprocal_rank_fusion(
        {
            RetrievalRoute.SEMANTIC: [
                hit(RetrievalRoute.SEMANTIC, "chunk-1", "one"),
                hit(RetrievalRoute.SEMANTIC, "chunk-2", "two"),
            ],
            RetrievalRoute.LEXICAL: [hit(RetrievalRoute.LEXICAL, "chunk-1", "one")],
        },
        rrf_k=60,
    )

    assert len(fused) == 2
    chunk_one = next(item for item in fused if item.id == "chunk-1")
    assert set(chunk_one.retrieval_routes) == {
        RetrievalRoute.SEMANTIC,
        RetrievalRoute.LEXICAL,
    }


def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=0.01)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
    sleep(0.02)
    breaker.before_call()
    state_after_reset = cast(CircuitState, breaker.state)
    assert state_after_reset == CircuitState.HALF_OPEN
    breaker.record_success()
    assert cast(CircuitState, breaker.state) == CircuitState.CLOSED
