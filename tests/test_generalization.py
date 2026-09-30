import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from enterprise_rag.generalization.models import GeneralizationDataset
from enterprise_rag.generalization.runner import GeneralizationRunner


def test_generalization_runner_records_inputs_expectations_and_actuals(
    client: TestClient,
) -> None:
    dataset = GeneralizationDataset.model_validate(
        {
            "version": 1,
            "description": "runner smoke test",
            "groups": [
                {
                    "id": "smoke",
                    "name": "冒烟",
                    "purpose": "验证报告结构",
                    "cases": [
                        {
                            "id": "ready",
                            "name": "就绪",
                            "scenario": "ready",
                            "input": {"path": "/health/ready"},
                            "expected": {"status_code": 200, "service_status": "ready"},
                            "criterion": "返回 ready",
                        },
                        {
                            "id": "empty",
                            "name": "空输入",
                            "scenario": "assistant",
                            "input": {"query": ""},
                            "expected": {"status_code": 422},
                            "criterion": "拒绝空输入",
                        },
                    ],
                }
            ],
        }
    )

    report = GeneralizationRunner(client, base_url=str(client.base_url)).run(dataset)

    assert report.status == "passed"
    assert report.total == 2
    assert report.passed == 2
    assert report.failed == 0
    assert report.groups[0].pass_rate == 1
    assert report.groups[0].cases[0].input == {"path": "/health/ready"}
    assert report.groups[0].cases[0].actual["service_status"] == "ready"


def test_full_generalization_dataset_exposes_known_gaps(client: TestClient) -> None:
    loaded: Any = json.loads(
        Path("evals/generalization-stability.json").read_text(encoding="utf-8")
    )
    dataset = GeneralizationDataset.model_validate(loaded)

    report = GeneralizationRunner(client, base_url=str(client.base_url)).run(dataset)

    assert report.status == "needs_attention"
    assert (report.total, report.passed, report.failed) == (34, 29, 5)
    assert {case.id for group in report.groups for case in group.cases if not case.passed} == {
        "linguistic_semantic_paraphrase",
        "linguistic_cross_language",
        "linguistic_typo_noise",
        "linguistic_context_followup",
        "boundary_whitespace_only",
    }
    assert next(group for group in report.groups if group.id == "typical").pass_rate == 1
    assert next(group for group in report.groups if group.id == "stability").pass_rate == 1
    assert any("hashing-v1" in limitation for limitation in report.limitations)
    assert any("Whitespace-only" in limitation for limitation in report.limitations)
