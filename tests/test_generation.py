import asyncio
import json
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient

from enterprise_rag.generation.audit import GroundedAnswerAuditor
from enterprise_rag.generation.models import GeneratedCandidate
from enterprise_rag.generation.repository import AnswerRecordRepository
from enterprise_rag.generation.service import AnswerGenerationService
from enterprise_rag.providers.base import GenerationRequest, GenerationResponse, ModelProvider
from enterprise_rag.rag.models import Citation, RagRetrievalResult, RetrievalRoute
from enterprise_rag.rag.service import RagService


class SequenceProvider(ModelProvider):
    name = "sequence"
    model = "sequence-v1"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        del request
        response = self.responses[self.calls]
        self.calls += 1
        return GenerationResponse(
            text=response,
            provider=self.name,
            model=self.model,
            finish_reason="stop",
        )


def _retrieval() -> RagRetrievalResult:
    citation = Citation(
        index=1,
        source_type="document",
        source_id="doc-1",
        title="车型手册",
        source_uri="kb://vehicle/range",
        snippet="星海 S7 的 CLTC 续航里程是 650 公里。",
        score=0.95,
        retrieval_routes=[RetrievalRoute.SEMANTIC, RetrievalRoute.LEXICAL],
    )
    return RagRetrievalResult(
        query="星海 S7 的 CLTC 续航是多少",
        hits=[],
        citations=[citation],
        context="[1] 车型手册\n星海 S7 的 CLTC 续航里程是 650 公里。",
        routes=[],
        duration_ms=1,
    )


def _payload(answer: str, score: float = 0.99) -> str:
    return json.dumps(
        {
            "answer": answer,
            "relevance_score": score,
            "accuracy_score": score,
        },
        ensure_ascii=False,
    )


def _service(provider: ModelProvider) -> AnswerGenerationService:
    repository = AnswerRecordRepository(Path("work/test-databases") / f"quality-{uuid4().hex}.db")
    repository.initialize()
    return AnswerGenerationService(
        rag=cast(RagService, object()),
        provider=provider,
        auditor=GroundedAnswerAuditor(min_grounding_coverage=0.15),
        repository=repository,
        self_score_threshold=0.90,
        post_audit_threshold=0.90,
        min_evidence_score=0.35,
        min_query_coverage=0.35,
        max_tokens=400,
        store_records=True,
    )


def test_rag_answer_api_returns_grounded_citations(client: TestClient) -> None:
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
    document_id = upload.json()["document"]["id"]

    response = client.post(
        "/api/v1/rag/answer",
        json={"query": "星海 S7 的 CLTC 续航是多少"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "answered"
    assert body["confidence"] == 0.99
    assert body["used_citation_indices"] == [1]
    assert body["citations"][0]["source_id"] == document_id
    assert body["attempts"][0]["passed"] is True
    assert body["record_id"]
    summary = client.get("/api/v1/rag/quality/summary")
    assert summary.status_code == 200
    assert summary.json() == {
        "total": 1,
        "answered": 1,
        "insufficient_evidence": 0,
        "needs_human": 0,
        "repaired": 0,
    }


def test_rag_answer_refuses_when_there_is_no_evidence(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rag/answer",
        json={"query": "不存在的车型有多少个量子推进器"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["confidence"] == 0
    assert body["attempts"] == []
    assert body["record_id"]


def test_generic_policy_words_do_not_turn_architecture_notes_into_refund_evidence(
    client: TestClient,
) -> None:
    """Regression for a real bad case: RRF rank is not evidence relevance."""
    upload = client.post(
        "/api/v1/knowledge/documents/ingest",
        files={
            "file": (
                "architecture.md",
                (
                    "# RAG 架构设计\\n\\n"
                    "FAQ 的数据质量会影响响应速度，质量门控用于保障回答可靠性。"
                ).encode(),
                "text/markdown",
            )
        },
        data={"source_uri": "kb://architecture/quality"},
    )
    assert upload.status_code == 200, upload.text

    response = client.post(
        "/api/v1/assistant/respond",
        json={"query": "退款政策是什么？"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert "退款" not in body["answer"] or "没有足够可靠" in body["answer"]


def test_refund_example_document_is_retrieved_when_it_explicitly_covers_the_query(
    client: TestClient,
) -> None:
    upload = client.post(
        "/api/v1/knowledge/documents/ingest",
        files={
            "file": (
                "refund-policy-example.md",
                (
                    "# 示例退款政策（仅用于系统验证）\\n\\n"
                    "本示例退款政策只用于 RAG 工作台测试，不构成真实企业承诺。\\n\\n"
                    "## 退款申请\\n\\n"
                    "本示例退款政策规定：未使用且未履约的订单可以申请退款；"
                    "系统核验订单、支付状态和服务使用记录后处理。\\n\\n"
                    "对未使用且未履约的订单，用户可以提交退款申请；"
                    "系统核验订单、支付状态和服务使用情况后处理。"
                ).encode(),
                "text/markdown",
            )
        },
        data={"source_uri": "kb://demo/refund-policy"},
    )
    assert upload.status_code == 200, upload.text

    response = client.post(
        "/api/v1/assistant/respond",
        json={"query": "退款政策是什么？"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "answered"
    assert "未使用" in body["answer"]
    assert body["retrieval"]["citations"][0]["query_coverage"] >= 0.35


def test_stream_only_emits_audited_answer(client: TestClient) -> None:
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

    with client.stream(
        "POST",
        "/api/v1/rag/answer/stream",
        json={"query": "星海 S7 的 CLTC 续航是多少"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: metadata" in body
    assert '"status": "answered"' in body
    assert "event: answer" in body
    assert "[1]" in body
    assert "event: done" in body


def test_failed_answer_is_repaired_once_and_persisted() -> None:
    provider = SequenceProvider(
        [
            _payload("星海 S7 的续航是 999 公里 [1]。"),
            _payload("星海 S7 的 CLTC 续航里程是 650 公里 [1]。"),
        ]
    )
    service = _service(provider)

    result = asyncio.run(service.answer("星海 S7 的 CLTC 续航是多少", retrieval=_retrieval()))

    assert result.status == "answered"
    assert result.repaired is True
    assert provider.calls == 2
    assert "unsupported_numeric_claim" in result.attempts[0].gates[1].reasons
    assert result.attempts[1].passed is True
    assert result.record_id is not None
    assert service.repository.count() == 1


def test_second_quality_failure_requires_human() -> None:
    provider = SequenceProvider(
        [
            _payload("一定赔偿 999 元 [1]。"),
            _payload("保证赔付 888 元 [1]。"),
        ]
    )
    service = _service(provider)

    result = asyncio.run(service.answer("星海 S7 的 CLTC 续航是多少", retrieval=_retrieval()))

    assert result.status == "needs_human"
    assert result.answer == "自动生成的答案未通过质量审核，建议转人工处理。"
    assert len(result.attempts) == 2
    assert all(not attempt.passed for attempt in result.attempts)


def test_auditor_rejects_invalid_citation_even_with_high_self_score() -> None:
    auditor = GroundedAnswerAuditor(min_grounding_coverage=0.15)
    candidate = GeneratedCandidate(
        answer="星海 S7 的 CLTC 续航里程是 650 公里 [9]。",
        relevance_score=0.99,
        accuracy_score=0.99,
    )

    gate = auditor.audit(
        "星海 S7 的 CLTC 续航是多少",
        candidate,
        _retrieval().citations,
        finish_reason="stop",
    )

    assert gate.passed is False
    assert "invalid_citation" in gate.reasons


def test_end_to_end_answer_evaluation(client: TestClient) -> None:
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
    document_id = upload.json()["document"]["id"]
    response = client.post(
        "/api/v1/rag/evaluate/answers",
        json={
            "cases": [
                {
                    "query": "星海 S7 的 CLTC 续航是多少",
                    "answerable": True,
                    "expected_phrases": ["650"],
                    "relevant_source_ids": [document_id],
                },
                {
                    "query": "qzxwvu banana flux capacitor",
                    "answerable": False,
                },
            ]
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["case_count"] == 2
    assert body["answer_success_rate"] == 1.0
    assert body["refusal_accuracy"] == 1.0
    assert body["citation_source_recall"] == 1.0
    assert body["p95_latency_ms"] >= body["p50_latency_ms"]
    assert all(case["passed"] for case in body["cases"])

