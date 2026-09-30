from fastapi.testclient import TestClient

from enterprise_rag.acceptance.runner import AcceptanceRunner


def test_complete_end_to_end_acceptance_suite(client: TestClient) -> None:
    report = AcceptanceRunner(client, base_url=str(client.base_url)).run()

    assert report.status == "passed", [
        (case.name, case.error) for case in report.cases if not case.passed
    ]
    assert report.total == 17
    assert report.passed == report.total
    assert report.failed == 0
    names = {case.name for case in report.cases}
    assert {
        "prompt_injection_rejected",
        "task_flow_action",
        "faq_exact",
        "kg_answer",
        "rag_grounded_answer",
        "insufficient_evidence",
        "unsafe_answer_escalates",
        "audited_sse",
        "answer_evaluation",
        "prometheus_metrics",
        "slo_snapshot",
    }.issubset(names)
