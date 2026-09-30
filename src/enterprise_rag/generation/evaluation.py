import math
from time import perf_counter

from enterprise_rag.generation.models import (
    AnswerEvaluationCase,
    AnswerEvaluationCaseResult,
    AnswerEvaluationResult,
)
from enterprise_rag.generation.service import AnswerGenerationService


class AnswerEvaluator:
    def __init__(self, service: AnswerGenerationService) -> None:
        self.service = service

    async def evaluate(self, cases: list[AnswerEvaluationCase]) -> AnswerEvaluationResult:
        results: list[AnswerEvaluationCaseResult] = []
        for case in cases:
            started = perf_counter()
            answer = await self.service.answer(case.query)
            duration_ms = (perf_counter() - started) * 1000
            missing_phrases = [
                phrase
                for phrase in case.expected_phrases
                if phrase.casefold() not in answer.answer.casefold()
            ]
            cited_source_ids = list(
                dict.fromkeys(citation.source_id for citation in answer.citations)
            )
            relevant = set(case.relevant_source_ids)
            citation_recall = (
                len(relevant.intersection(cited_source_ids)) / len(relevant) if relevant else 1.0
            )
            if case.answerable:
                passed = (
                    answer.status == "answered" and not missing_phrases and citation_recall == 1.0
                )
            else:
                passed = answer.status != "answered"
            results.append(
                AnswerEvaluationCaseResult(
                    query=case.query,
                    expected_answerable=case.answerable,
                    actual_status=answer.status,
                    passed=passed,
                    missing_phrases=missing_phrases,
                    cited_source_ids=cited_source_ids,
                    citation_source_recall=citation_recall,
                    confidence=answer.confidence,
                    repaired=answer.repaired,
                    duration_ms=duration_ms,
                )
            )

        answerable = [item for item in results if item.expected_answerable]
        unanswerable = [item for item in results if not item.expected_answerable]
        latencies = [item.duration_ms for item in results]
        count = len(results)
        return AnswerEvaluationResult(
            case_count=count,
            answer_success_rate=self._pass_rate(answerable),
            refusal_accuracy=self._pass_rate(unanswerable),
            citation_source_recall=(
                sum(item.citation_source_recall for item in answerable) / len(answerable)
                if answerable
                else 1.0
            ),
            average_confidence=(sum(item.confidence for item in results) / count if count else 0.0),
            repair_rate=(sum(item.repaired for item in results) / count if count else 0.0),
            human_escalation_rate=(
                sum(item.actual_status == "needs_human" for item in results) / count
                if count
                else 0.0
            ),
            p50_latency_ms=self._percentile(latencies, 0.50),
            p95_latency_ms=self._percentile(latencies, 0.95),
            cases=results,
        )

    def _pass_rate(self, cases: list[AnswerEvaluationCaseResult]) -> float:
        return sum(case.passed for case in cases) / len(cases) if cases else 1.0

    def _percentile(self, values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return ordered[max(math.ceil(len(ordered) * percentile) - 1, 0)]
