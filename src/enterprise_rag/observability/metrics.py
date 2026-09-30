import math
from collections import Counter, defaultdict, deque
from threading import Lock

from enterprise_rag.observability.models import SloCheck, SloSnapshot

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class MetricsRegistry:
    def __init__(self, *, max_latency_samples: int = 10000) -> None:
        self._http_counts: Counter[tuple[str, str, int]] = Counter()
        self._answer_counts: Counter[tuple[str, bool]] = Counter()
        self._retrieval_counts: Counter[tuple[str, str]] = Counter()
        self._http_latencies: deque[float] = deque(maxlen=max_latency_samples)
        self._answer_latencies: deque[float] = deque(maxlen=max_latency_samples)
        self._retrieval_latencies: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=max_latency_samples)
        )
        self._lock = Lock()

    def record_http(self, method: str, route: str, status: int, duration_seconds: float) -> None:
        with self._lock:
            self._http_counts[(method, route, status)] += 1
            self._http_latencies.append(duration_seconds)

    def record_answer(self, status: str, repaired: bool, duration_seconds: float) -> None:
        with self._lock:
            self._answer_counts[(status, repaired)] += 1
            self._answer_latencies.append(duration_seconds)

    def record_retrieval(self, route: str, status: str, duration_seconds: float) -> None:
        with self._lock:
            self._retrieval_counts[(route, status)] += 1
            self._retrieval_latencies[route].append(duration_seconds)

    def slo_snapshot(
        self,
        *,
        availability_target: float,
        p95_latency_ms_target: float,
        answer_success_target: float,
    ) -> SloSnapshot:
        with self._lock:
            http_counts = self._http_counts.copy()
            answer_counts = self._answer_counts.copy()
            latencies = list(self._http_latencies)
        request_total = sum(http_counts.values())
        successful_requests = sum(
            count for (_, _, status), count in http_counts.items() if status < 500
        )
        answer_total = sum(answer_counts.values())
        answered = sum(
            count for (status, _), count in answer_counts.items() if status == "answered"
        )
        needs_human = sum(
            count for (status, _), count in answer_counts.items() if status == "needs_human"
        )
        availability = successful_requests / request_total if request_total else None
        p95_ms = self._percentile(latencies, 0.95) * 1000 if latencies else None
        auditable_answers = answered + needs_human
        answer_success = answered / auditable_answers if auditable_answers else None
        checks = [
            self._ratio_check("availability", availability_target, availability),
            self._latency_check("http_p95_latency", p95_latency_ms_target, p95_ms),
            self._ratio_check("answer_success", answer_success_target, answer_success),
        ]
        evaluated = [check for check in checks if check.passed is not None]
        status = (
            "no_data"
            if not evaluated
            else "healthy"
            if all(check.passed for check in evaluated)
            else "violated"
        )
        return SloSnapshot(
            status=status,
            request_samples=request_total,
            answer_samples=answer_total,
            checks=checks,
        )

    def render_prometheus(self) -> str:
        with self._lock:
            http_counts = sorted(self._http_counts.items())
            answer_counts = sorted(self._answer_counts.items())
            retrieval_counts = sorted(self._retrieval_counts.items())
            http_latencies = list(self._http_latencies)
            answer_latencies = list(self._answer_latencies)
            retrieval_latencies = {
                route: list(values) for route, values in self._retrieval_latencies.items()
            }
        lines = [
            "# HELP enterprise_rag_http_requests_total HTTP requests handled.",
            "# TYPE enterprise_rag_http_requests_total counter",
        ]
        for (method, route, status), count in http_counts:
            lines.append(
                "enterprise_rag_http_requests_total"
                f'{{method="{_escape(method)}",route="{_escape(route)}",status="{status}"}} '
                f"{count}"
            )
        lines.extend(
            self._histogram("enterprise_rag_http_request_duration_seconds", http_latencies)
        )
        lines.extend(
            [
                "# HELP enterprise_rag_answers_total Final answer outcomes.",
                "# TYPE enterprise_rag_answers_total counter",
            ]
        )
        for (answer_status, repaired), count in answer_counts:
            lines.append(
                "enterprise_rag_answers_total"
                f'{{status="{_escape(answer_status)}",'
                f'repaired="{str(repaired).lower()}"}} {count}'
            )
        lines.extend(self._histogram("enterprise_rag_answer_duration_seconds", answer_latencies))
        lines.extend(
            [
                "# HELP enterprise_rag_retrieval_routes_total Retrieval route outcomes.",
                "# TYPE enterprise_rag_retrieval_routes_total counter",
            ]
        )
        for (route, retrieval_status), count in retrieval_counts:
            lines.append(
                "enterprise_rag_retrieval_routes_total"
                f'{{route="{_escape(route)}",'
                f'status="{_escape(retrieval_status)}"}} {count}'
            )
        for route, values in sorted(retrieval_latencies.items()):
            lines.append(
                "enterprise_rag_retrieval_route_duration_seconds_sum"
                f'{{route="{_escape(route)}"}} {sum(values):.9f}'
            )
            lines.append(
                "enterprise_rag_retrieval_route_duration_seconds_count"
                f'{{route="{_escape(route)}"}} {len(values)}'
            )
        return "\n".join(lines) + "\n"

    def _histogram(self, name: str, values: list[float]) -> list[str]:
        lines = [f"# TYPE {name} histogram"]
        for bucket in _BUCKETS:
            count = sum(value <= bucket for value in values)
            lines.append(f'{name}_bucket{{le="{bucket:g}"}} {count}')
        lines.append(f'{name}_bucket{{le="+Inf"}} {len(values)}')
        lines.append(f"{name}_sum {sum(values):.9f}")
        lines.append(f"{name}_count {len(values)}")
        return lines

    def _percentile(self, values: list[float], percentile: float) -> float:
        ordered = sorted(values)
        index = max(math.ceil(len(ordered) * percentile) - 1, 0)
        return ordered[index]

    def _ratio_check(self, name: str, target: float, actual: float | None) -> SloCheck:
        return SloCheck(
            name=name,
            target=target,
            actual=actual,
            unit="ratio",
            passed=None if actual is None else actual >= target,
        )

    def _latency_check(self, name: str, target: float, actual: float | None) -> SloCheck:
        return SloCheck(
            name=name,
            target=target,
            actual=actual,
            unit="milliseconds",
            passed=None if actual is None else actual <= target,
        )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
