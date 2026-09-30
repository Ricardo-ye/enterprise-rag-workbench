import json
import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

from enterprise_rag.generalization.models import (
    GeneralizationCase,
    GeneralizationCaseResult,
    GeneralizationDataset,
    GeneralizationGroupResult,
    GeneralizationReport,
)

ScenarioHandler = Callable[[GeneralizationCase], dict[str, Any]]


class CaseExpectationError(AssertionError):
    def __init__(self, message: str, actual: dict[str, Any]) -> None:
        super().__init__(message)
        self.actual = actual


class GeneralizationRunner:
    """Execute a declarative validation dataset against a running service."""

    def __init__(self, client: httpx.Client, *, base_url: str) -> None:
        self.client = client
        self.base_url = base_url
        self.run_id = uuid4().hex[:12]
        self._handlers: dict[str, ScenarioHandler] = {
            "ready": self._ready,
            "assistant": self._assistant,
            "route": self._route,
            "malformed_json": self._malformed_json,
            "unsupported_upload": self._unsupported_upload,
            "invalid_utf8_upload": self._invalid_utf8_upload,
            "missing_document": self._missing_document,
            "idempotent_ingest": self._idempotent_ingest,
            "sql_injection_resilience": self._sql_injection_resilience,
            "xss_rendering_safety": self._xss_rendering_safety,
            "repeat_route": self._repeat_route,
            "concurrent_readiness": self._concurrent_readiness,
            "repeat_search": self._repeat_search,
            "repeat_rebuild": self._repeat_rebuild,
            "multiturn_task": self._multiturn_task,
        }

    def run(self, dataset: GeneralizationDataset) -> GeneralizationReport:
        started = perf_counter()
        setup = self._seed_knowledge()
        groups: list[GeneralizationGroupResult] = []
        all_results: list[GeneralizationCaseResult] = []
        for group in dataset.groups:
            results = [self._run_case(case) for case in group.cases]
            passed = sum(result.passed for result in results)
            groups.append(
                GeneralizationGroupResult(
                    id=group.id,
                    name=group.name,
                    purpose=group.purpose,
                    total=len(results),
                    passed=passed,
                    failed=len(results) - passed,
                    pass_rate=passed / len(results),
                    cases=results,
                )
            )
            all_results.extend(results)
        passed = sum(result.passed for result in all_results)
        failures = [result for result in all_results if not result.passed]
        return GeneralizationReport(
            generated_at=datetime.now(UTC),
            base_url=self.base_url,
            status="passed" if not failures else "needs_attention",
            total=len(all_results),
            passed=passed,
            failed=len(failures),
            pass_rate=passed / len(all_results) if all_results else 0,
            duration_ms=(perf_counter() - started) * 1000,
            setup=setup,
            groups=groups,
            limitations=self._limitations(failures),
            known_boundaries=[
                "The default hashing-v1 embedding is lexical and is not a production "
                "semantic model.",
                "The deterministic mock generator validates orchestration, not real-model "
                "answer quality.",
                "The suite runs on SQLite in one service instance; distributed consistency "
                "is not covered.",
                "External model, SearXNG, container, and network failure modes require "
                "environment tests.",
            ],
        )

    def _run_case(self, case: GeneralizationCase) -> GeneralizationCaseResult:
        started = perf_counter()
        actual: dict[str, Any] = {}
        try:
            handler = self._handlers[case.scenario]
            actual = handler(case)
        except Exception as exc:
            if isinstance(exc, CaseExpectationError):
                actual = exc.actual
            return GeneralizationCaseResult(
                id=case.id,
                name=case.name,
                scenario=case.scenario,
                passed=False,
                duration_ms=(perf_counter() - started) * 1000,
                input=case.input,
                expected=case.expected,
                criterion=case.criterion,
                actual=actual,
                error=f"{type(exc).__name__}: {exc}",
            )
        return GeneralizationCaseResult(
            id=case.id,
            name=case.name,
            scenario=case.scenario,
            passed=True,
            duration_ms=(perf_counter() - started) * 1000,
            input=case.input,
            expected=case.expected,
            criterion=case.criterion,
            actual=actual,
        )

    def _seed_knowledge(self) -> list[dict[str, Any]]:
        documents = [
            (
                "architecture.md",
                "# 企业 RAG 质量门控\n\n质量门控会校验引用、事实一致性、合规性和答案完整性。",
                "architecture",
            ),
            (
                "s7.md",
                "# 星海 S7 参数\n\n星海 S7 的 CLTC 续航里程是 650 公里。",
                "s7",
            ),
            (
                "s9.md",
                "# 星海 S9 参数\n\n星海 S9 的 CLTC 续航里程是 800 公里。",
                "s9",
            ),
            (
                "winter-range.md",
                "# 冬季续航\n\n低温环境会降低锂离子活性，导致冬季续航里程缩短。",
                "winter",
            ),
            (
                "privacy.md",
                "# 隐私规范\n\n客户手机号只用于已授权的服务预约，不得用于营销外呼。",
                "privacy",
            ),
        ]
        setup: list[dict[str, Any]] = []
        for filename, content, suffix in documents:
            response = self.client.post(
                "/api/v1/knowledge/documents/ingest",
                files={"file": (filename, content.encode(), "text/markdown")},
                data={"source_uri": f"generalization://{self.run_id}/{suffix}"},
            )
            setup.append(
                {
                    "resource": filename,
                    "status_code": response.status_code,
                    "ok": response.status_code == 200,
                }
            )
        faq = self.client.post(
            "/api/v1/knowledge/faqs/import",
            json={
                "items": [
                    {
                        "question": "预约保养需要提前多久?",
                        "answer": "建议至少提前一天预约。",
                        "approved": True,
                        "metadata": {"suite": "generalization"},
                    }
                ]
            },
        )
        setup.append(
            {"resource": "approved_faq", "status_code": faq.status_code, "ok": faq.is_success}
        )
        kg = self.client.post(
            "/api/v1/kbqa/kg/triples/import",
            json={
                "triples": [
                    {
                        "subject": "星海 S7",
                        "predicate": "CLTC 续航",
                        "object": "650 公里",
                        "subject_aliases": ["S7"],
                        "predicate_aliases": ["续航", "续航里程"],
                        "metadata": {"suite": "generalization"},
                    }
                ]
            },
        )
        setup.append(
            {"resource": "knowledge_graph", "status_code": kg.status_code, "ok": kg.is_success}
        )
        if not all(bool(item["ok"]) for item in setup):
            raise RuntimeError(f"generalization setup failed: {setup}")
        return setup

    def _ready(self, case: GeneralizationCase) -> dict[str, Any]:
        response = self.client.get("/health/ready")
        body = self._json(response)
        self._expect_status(response, int(case.expected["status_code"]))
        self._expect_equal(body.get("status"), case.expected.get("service_status"), "status")
        return {"status_code": response.status_code, "service_status": body.get("status")}

    def _assistant(self, case: GeneralizationCase) -> dict[str, Any]:
        payload = self._expanded_payload(case.input)
        response = self.client.post("/api/v1/assistant/respond", json=payload)
        expected_status = int(case.expected.get("status_code", 200))
        actual: dict[str, Any] = {
            "status_code": response.status_code,
            "query_length": len(str(payload.get("query", ""))),
        }
        body: Any = None
        if response.status_code == 200:
            body = self._json(response)
            route = body.get("route") or {}
            safety = route.get("safety") or {}
            kbqa = body.get("kbqa") or {}
            actual.update(
                {
                    "assistant_status": body.get("status"),
                    "answer": body.get("answer"),
                    "route_target": route.get("target"),
                    "safety_decision": safety.get("decision"),
                    "kbqa_path": kbqa.get("path"),
                }
            )
        try:
            self._expect_status(response, expected_status)
        except AssertionError as exc:
            if response.status_code != 200:
                actual["body"] = self._safe_body(response)
            raise CaseExpectationError(str(exc), actual) from exc
        if response.status_code != 200:
            actual["body"] = self._safe_body(response)
            return actual
        assert isinstance(body, dict)
        route = body.get("route") or {}
        safety = route.get("safety") or {}
        kbqa = body.get("kbqa") or {}
        try:
            self._check_optional(body.get("status"), case.expected, "assistant_status")
            self._check_optional(route.get("target"), case.expected, "route_target")
            self._check_optional(safety.get("decision"), case.expected, "safety_decision")
            self._check_optional(kbqa.get("path"), case.expected, "kbqa_path")
            if "answer_contains" in case.expected:
                expected_text = str(case.expected["answer_contains"])
                assert expected_text in str(body.get("answer", "")), (
                    f"answer does not contain {expected_text!r}"
                )
        except AssertionError as exc:
            raise CaseExpectationError(str(exc), actual) from exc
        return actual

    def _route(self, case: GeneralizationCase) -> dict[str, Any]:
        payload = self._expanded_payload(case.input)
        if "history" in payload and "context" not in payload:
            payload["context"] = {"history": payload.pop("history")}
        response = self.client.post("/api/v1/routing/route", json=payload)
        expected_status = int(case.expected.get("status_code", 200))
        self._expect_status(response, expected_status)
        actual: dict[str, Any] = {"status_code": response.status_code}
        if response.status_code != 200:
            actual["body"] = self._safe_body(response)
            return actual
        body = self._json(response)
        safety = body.get("safety") or {}
        actual.update(
            {
                "target": body.get("target"),
                "intent": (body.get("intent") or {}).get("name"),
                "safety_decision": safety.get("decision"),
                "normalized_query_length": len(str(body.get("normalized_query", ""))),
            }
        )
        self._check_optional(body.get("target"), case.expected, "target")
        self._check_optional((body.get("intent") or {}).get("name"), case.expected, "intent")
        self._check_optional(safety.get("decision"), case.expected, "safety_decision")
        return actual

    def _malformed_json(self, case: GeneralizationCase) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/assistant/respond",
            content=str(case.input["raw_body"]),
            headers={"Content-Type": "application/json"},
        )
        self._expect_status(response, int(case.expected["status_code"]))
        return {"status_code": response.status_code, "body": self._safe_body(response)}

    def _unsupported_upload(self, case: GeneralizationCase) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/knowledge/documents/ingest",
            files={"file": (str(case.input["filename"]), b"not-an-image", "image/png")},
        )
        self._expect_status(response, int(case.expected["status_code"]))
        return {"status_code": response.status_code, "body": self._safe_body(response)}

    def _invalid_utf8_upload(self, case: GeneralizationCase) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/knowledge/documents/ingest",
            files={"file": (str(case.input["filename"]), b"\xff\xfe\x00\x80", "text/plain")},
        )
        self._expect_status(response, int(case.expected["status_code"]))
        return {"status_code": response.status_code, "body": self._safe_body(response)}

    def _missing_document(self, case: GeneralizationCase) -> dict[str, Any]:
        response = self.client.delete(
            f"/api/v1/knowledge/documents/{case.input['document_id']}"
        )
        self._expect_status(response, int(case.expected["status_code"]))
        return {"status_code": response.status_code, "body": self._safe_body(response)}

    def _idempotent_ingest(self, case: GeneralizationCase) -> dict[str, Any]:
        content = f"{case.input['content']}\n\nRun: {self.run_id}"
        source_uri = f"generalization://{self.run_id}/idempotent"

        def upload() -> httpx.Response:
            return self.client.post(
                "/api/v1/knowledge/documents/ingest",
                files={"file": ("idempotent.md", content.encode(), "text/markdown")},
                data={"source_uri": source_uri},
            )

        first = upload()
        second = upload()
        self._expect_status(first, 200)
        self._expect_status(second, 200)
        actions = [self._json(first).get("action"), self._json(second).get("action")]
        self._expect_equal(actions, case.expected["actions"], "ingestion actions")
        return {"status_codes": [first.status_code, second.status_code], "actions": actions}

    def _sql_injection_resilience(self, case: GeneralizationCase) -> dict[str, Any]:
        before_response = self.client.get("/api/v1/knowledge/documents")
        self._expect_status(before_response, 200)
        before = len(self._json(before_response))
        response = self.client.post(
            "/api/v1/knowledge/search",
            json={"query": str(case.input["query"]), "limit": 5},
        )
        after_response = self.client.get("/api/v1/knowledge/documents")
        self._expect_status(after_response, 200)
        after = len(self._json(after_response))
        expected_status = int(case.expected["status_code"])
        self._expect_status(response, expected_status)
        self._expect_equal(after, before, "document count after injection-shaped query")
        return {
            "status_code": response.status_code,
            "documents_before": before,
            "documents_after": after,
            "body": self._safe_body(response),
        }

    def _xss_rendering_safety(self, case: GeneralizationCase) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/assistant/respond", json={"query": str(case.input["query"])}
        )
        script = self.client.get("/assets/app.js")
        self._expect_status(response, int(case.expected["status_code"]))
        self._expect_status(script, 200)
        assert "textContent" in script.text, "UI does not expose a textContent rendering path"
        assert "createElement" in script.text, "UI does not build dynamic nodes safely"
        return {
            "status_code": response.status_code,
            "uses_text_content": True,
            "uses_dom_node_creation": True,
        }

    def _repeat_route(self, case: GeneralizationCase) -> dict[str, Any]:
        iterations = int(case.input["iterations"])
        signatures: list[tuple[str | None, str | None, str | None]] = []
        latencies: list[float] = []
        statuses: list[int] = []
        for _ in range(iterations):
            started = perf_counter()
            response = self.client.post(
                "/api/v1/routing/route", json={"query": str(case.input["query"])}
            )
            latencies.append((perf_counter() - started) * 1000)
            statuses.append(response.status_code)
            if response.status_code == 200:
                body = self._json(response)
                signatures.append(
                    (
                        body.get("target"),
                        (body.get("intent") or {}).get("name"),
                        (body.get("safety") or {}).get("decision"),
                    )
                )
        assert statuses == [200] * iterations, "one or more repeated requests failed"
        assert len(set(signatures)) == 1, "routing decisions changed across identical requests"
        p95 = self._percentile(latencies, 0.95)
        assert p95 <= float(case.expected["p95_max_ms"]), (
            f"route p95 {p95:.2f}ms exceeds threshold"
        )
        expected_target = str(case.expected["target"])
        assert signatures[0][0] == expected_target, f"expected target {expected_target}"
        return {
            "iterations": iterations,
            "successes": statuses.count(200),
            "stable_signature": list(signatures[0]),
            "p95_ms": p95,
        }

    def _concurrent_readiness(self, case: GeneralizationCase) -> dict[str, Any]:
        requests = int(case.input["requests"])
        workers = int(case.input["workers"])

        def request_once(_: int) -> tuple[int, float]:
            started = perf_counter()
            response = self.client.get("/health/ready")
            return response.status_code, (perf_counter() - started) * 1000

        with ThreadPoolExecutor(max_workers=workers) as executor:
            samples = list(executor.map(request_once, range(requests)))
        statuses = [sample[0] for sample in samples]
        latencies = [sample[1] for sample in samples]
        assert statuses == [200] * requests, "one or more concurrent readiness calls failed"
        p95 = self._percentile(latencies, 0.95)
        assert p95 <= float(case.expected["p95_max_ms"]), (
            f"readiness p95 {p95:.2f}ms exceeds threshold"
        )
        return {
            "requests": requests,
            "workers": workers,
            "successes": statuses.count(200),
            "p95_ms": p95,
        }

    def _repeat_search(self, case: GeneralizationCase) -> dict[str, Any]:
        iterations = int(case.input["iterations"])
        rankings: list[list[str]] = []
        for _ in range(iterations):
            response = self.client.post(
                "/api/v1/knowledge/search",
                json={"query": str(case.input["query"]), "limit": 5},
            )
            self._expect_status(response, 200)
            body = self._json(response)
            rankings.append(
                [str(hit["source_id"]) for hit in body.get("vector", [])]
            )
        assert rankings[0], "search returned no vector results"
        assert all(ranking == rankings[0] for ranking in rankings), (
            "search ranking changed across identical requests"
        )
        return {"iterations": iterations, "stable": True, "ranking": rankings[0]}

    def _repeat_rebuild(self, case: GeneralizationCase) -> dict[str, Any]:
        iterations = int(case.input["iterations"])
        summaries: list[dict[str, Any]] = []
        for _ in range(iterations):
            response = self.client.post("/api/v1/knowledge/indexes/rebuild")
            self._expect_status(response, 200)
            summaries.append(self._json(response))
        comparable = [
            (item.get("status"), item.get("documents"), item.get("chunks"), item.get("faqs"))
            for item in summaries
        ]
        assert len(set(comparable)) == 1, "index rebuild counts drifted across repetitions"
        return {"iterations": iterations, "stable_summary": summaries[0]}

    def _multiturn_task(self, case: GeneralizationCase) -> dict[str, Any]:
        conversation_id = f"generalization-task-{self.run_id}"
        statuses: list[str] = []
        for query in case.input["turns"]:
            response = self.client.post(
                "/api/v1/assistant/respond",
                json={"query": str(query), "conversation_id": conversation_id},
            )
            self._expect_status(response, 200)
            statuses.append(str(self._json(response).get("status")))
        self._expect_equal(statuses, case.expected["statuses"], "multi-turn statuses")
        return {"turns": len(statuses), "statuses": statuses}

    def _expanded_payload(self, source: dict[str, Any]) -> dict[str, Any]:
        payload = dict(source)
        if "query_fragment" in payload:
            fragment = str(payload.pop("query_fragment"))
            count = int(payload.pop("repeat_count"))
            payload["query"] = fragment * count
        if "history_count" in payload:
            count = int(payload.pop("history_count"))
            payload["history"] = [
                {"role": "user", "content": f"历史问题 {index}"} for index in range(count)
            ]
        return payload

    def _expect_status(self, response: httpx.Response, expected: int) -> None:
        assert response.status_code == expected, (
            f"expected HTTP {expected}, got {response.status_code}: {response.text[:500]}"
        )

    def _json(self, response: httpx.Response) -> Any:
        return response.json()

    def _safe_body(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text[:500]

    def _expect_equal(self, actual: Any, expected: Any, field: str) -> None:
        assert actual == expected, f"{field}: expected {expected!r}, got {actual!r}"

    def _check_optional(self, actual: Any, expected: dict[str, Any], field: str) -> None:
        if field in expected:
            self._expect_equal(actual, expected[field], field)

    def _percentile(self, values: list[float], quantile: float) -> float:
        ordered = sorted(values)
        index = max(0, math.ceil(len(ordered) * quantile) - 1)
        return ordered[index]

    def _limitations(self, failures: list[GeneralizationCaseResult]) -> list[str]:
        if not failures:
            return []
        limitations: list[str] = []
        failed_ids = {failure.id for failure in failures}
        language_ids = {
            "linguistic_semantic_paraphrase",
            "linguistic_cross_language",
            "linguistic_typo_noise",
            "linguistic_context_followup",
        }
        if failed_ids & language_ids:
            limitations.append(
                "Semantic generalization is limited by hashing-v1 embeddings and literal "
                "routing rules; paraphrases, cross-language queries, typos, or ellipsis may "
                "lose the intended evidence."
            )
        if "boundary_whitespace_only" in failed_ids:
            limitations.append(
                "Whitespace-only queries pass schema length validation and should be "
                "rejected after normalization."
            )
        if "security_sql_shaped_search" in failed_ids:
            limitations.append(
                "FTS query syntax is not normalized defensively enough; injection-shaped input can "
                "produce a server error even when parameterization prevents data loss."
            )
        if failed_ids - language_ids - {
            "boundary_whitespace_only",
            "security_sql_shaped_search",
        }:
            limitations.append(
                "Additional failed cases require case-level review in the report before "
                "production use."
            )
        return limitations
