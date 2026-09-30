from fastapi.testclient import TestClient


def _import_faq(
    client: TestClient,
    *,
    question: str,
    answer: str,
    approved: bool = True,
) -> None:
    response = client.post(
        "/api/v1/knowledge/faqs/import",
        json={
            "items": [
                {
                    "question": question,
                    "answer": answer,
                    "approved": approved,
                    "metadata": {"owner": "qa-team"},
                }
            ]
        },
    )
    assert response.status_code == 200, response.text


def test_approved_exact_faq_bypasses_runtime_gates(client: TestClient) -> None:
    _import_faq(
        client,
        question="整车保修期是多久?",
        answer="整车保修期以购车合同和保修手册为准。",
    )
    response = client.post(
        "/api/v1/kbqa/query",
        json={"query": "整车保修期是多久？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["path"] == "faq_exact"
    assert body["direct"] is True
    assert body["gates"] == []


def test_unapproved_faq_cannot_use_exact_fast_path(client: TestClient) -> None:
    _import_faq(
        client,
        question="内部折扣是多少?",
        answer="该信息仅供内部使用。",
        approved=False,
    )
    response = client.post(
        "/api/v1/kbqa/query",
        json={"query": "内部折扣是多少?"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "fallback"
    assert response.json()["target"] == "rag"


def test_faq_recall_passes_double_gate_for_near_exact_question(client: TestClient) -> None:
    _import_faq(
        client,
        question="预约保养需要提前多久?",
        answer="建议至少提前一天预约。",
    )
    response = client.post(
        "/api/v1/kbqa/query",
        json={"query": "预约保养需要提前多久呢?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["path"] == "faq_recall"
    assert body["direct"] is False
    assert [gate["passed"] for gate in body["gates"]] == [True, True, True]


def test_answer_audit_rejects_risky_commitment(client: TestClient) -> None:
    _import_faq(
        client,
        question="事故后一定会赔吗?",
        answer="我们保证赔付全部损失。",
    )
    response = client.post(
        "/api/v1/kbqa/query",
        json={"query": "事故后一定会赔吗呢?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fallback"
    assert body["target"] == "rag"
    assert any("risky_commitment" in gate["reasons"] for gate in body["gates"])


def test_kg_query_returns_structured_fact_through_both_gates(client: TestClient) -> None:
    imported = client.post(
        "/api/v1/kbqa/kg/triples/import",
        json={
            "triples": [
                {
                    "subject": "星海 S7",
                    "predicate": "CLTC 续航里程",
                    "object": "650 公里",
                    "subject_aliases": ["S7"],
                    "predicate_aliases": ["续航", "能跑多远"],
                    "metadata": {"source": "车型参数表"},
                }
            ]
        },
    )
    assert imported.status_code == 200
    assert imported.json() == {"created": 1, "updated": 0}

    response = client.post(
        "/api/v1/kbqa/query",
        json={"query": "星海 S7 的 CLTC 续航里程是多少?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["path"] == "kg"
    assert "650 公里" in body["answer"]
    assert [gate["passed"] for gate in body["gates"]] == [True, True, True]


def test_assistant_wires_routing_to_exact_faq(client: TestClient) -> None:
    _import_faq(
        client,
        question="保修期多久?",
        answer="请以随车保修手册为准。",
    )
    response = client.post(
        "/api/v1/assistant/respond",
        json={"query": "保修期多久?", "conversation_id": "conversation-kbqa-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"]["target"] == "kbqa"
    assert body["status"] == "answered"
    assert body["kbqa"]["path"] == "faq_exact"


def test_assistant_distinguishes_maintenance_question_from_booking(client: TestClient) -> None:
    _import_faq(
        client,
        question="预约保养需要提前多久?",
        answer="建议至少提前一天预约。",
    )
    response = client.post(
        "/api/v1/assistant/respond",
        json={
            "query": "预约保养需要提前多久?",
            "conversation_id": "conversation-maintenance-faq",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"]["intent"]["name"] == "maintenance_policy_query"
    assert body["route"]["target"] == "kbqa"
    assert body["status"] == "answered"
    assert body["task"] is None
