import asyncio
from time import perf_counter

from enterprise_rag.generation.audit import GroundedAnswerAuditor
from enterprise_rag.generation.models import (
    GeneratedCandidate,
    GenerationAttempt,
    QualityGate,
    RagAnswerResult,
)
from enterprise_rag.generation.parser import GenerationParseError, citation_indices, parse_candidate
from enterprise_rag.generation.prompts import build_generation_request, build_repair_request
from enterprise_rag.generation.repository import AnswerRecordRepository
from enterprise_rag.observability.metrics import MetricsRegistry
from enterprise_rag.providers.base import GenerationRequest, ModelProvider
from enterprise_rag.rag.models import Citation, RagRetrievalResult
from enterprise_rag.rag.service import RagService


class AnswerGenerationService:
    def __init__(
        self,
        *,
        rag: RagService,
        provider: ModelProvider,
        auditor: GroundedAnswerAuditor,
        repository: AnswerRecordRepository,
        self_score_threshold: float,
        post_audit_threshold: float,
        min_evidence_score: float,
        min_query_coverage: float,
        max_tokens: int,
        store_records: bool,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.rag = rag
        self.provider = provider
        self.auditor = auditor
        self.repository = repository
        self.self_score_threshold = self_score_threshold
        self.post_audit_threshold = post_audit_threshold
        self.min_evidence_score = min_evidence_score
        self.min_query_coverage = min_query_coverage
        self.max_tokens = max_tokens
        self.store_records = store_records
        self.metrics = metrics

    async def answer(
        self,
        query: str,
        *,
        retrieval: RagRetrievalResult | None = None,
    ) -> RagAnswerResult:
        started = perf_counter()
        result = await self._answer(query, retrieval=retrieval)
        if self.metrics:
            self.metrics.record_answer(
                result.status,
                result.repaired,
                perf_counter() - started,
            )
        return result

    async def _answer(
        self,
        query: str,
        *,
        retrieval: RagRetrievalResult | None = None,
    ) -> RagAnswerResult:
        if retrieval is None:
            evidence_result = await asyncio.to_thread(self.rag.retrieve, query)
        else:
            evidence_result = retrieval
        eligible_citations = [
            citation
            for citation in evidence_result.citations
            if (
                citation.score >= self.min_evidence_score
                and citation.query_coverage >= self.min_query_coverage
            )
        ]
        if not eligible_citations:
            return await self._finalize(
                RagAnswerResult(
                    query=query,
                    status="insufficient_evidence",
                    answer="当前知识库中没有足够可靠的证据回答该问题。",
                    confidence=0.0,
                    retrieval=evidence_result,
                )
            )

        prompt_retrieval = evidence_result.model_copy(
            update={
                "citations": eligible_citations,
                "context": self._context(eligible_citations),
            }
        )
        initial_request = build_generation_request(
            query,
            prompt_retrieval,
            max_tokens=self.max_tokens,
        )
        initial = await self._attempt(
            query,
            eligible_citations,
            initial_request,
            attempt_number=1,
            kind="initial",
        )
        attempts = [initial]
        if initial.passed and initial.candidate:
            return await self._answered(
                query,
                evidence_result,
                eligible_citations,
                attempts,
                initial.candidate,
                repaired=False,
            )

        repair_request = build_repair_request(
            query,
            prompt_retrieval,
            initial.candidate,
            initial,
            max_tokens=self.max_tokens,
        )
        repaired = await self._attempt(
            query,
            eligible_citations,
            repair_request,
            attempt_number=2,
            kind="repair",
        )
        attempts.append(repaired)
        if repaired.passed and repaired.candidate:
            return await self._answered(
                query,
                evidence_result,
                eligible_citations,
                attempts,
                repaired.candidate,
                repaired=True,
            )

        return await self._finalize(
            RagAnswerResult(
                query=query,
                status="needs_human",
                answer="自动生成的答案未通过质量审核，建议转人工处理。",
                confidence=0.0,
                retrieval=evidence_result,
                attempts=attempts,
                repaired=True,
            )
        )

    async def _attempt(
        self,
        query: str,
        citations: list[Citation],
        request: GenerationRequest,
        *,
        attempt_number: int,
        kind: str,
    ) -> GenerationAttempt:
        response = await self.provider.generate(request)
        try:
            candidate = parse_candidate(response.text)
        except GenerationParseError as exc:
            return GenerationAttempt(
                attempt=attempt_number,
                kind="initial" if kind == "initial" else "repair",
                provider=response.provider,
                model=response.model,
                finish_reason=response.finish_reason,
                passed=False,
                error=str(exc),
            )

        first_gate = self._self_score_gate(candidate)
        gates = [first_gate]
        if first_gate.passed:
            audit = self.auditor.audit(
                query,
                candidate,
                citations,
                finish_reason=response.finish_reason,
            )
            gates.append(audit)
            if audit.passed:
                gates.append(self._post_audit_gate(audit))
        passed = bool(gates and len(gates) == 3 and all(gate.passed for gate in gates))
        return GenerationAttempt(
            attempt=attempt_number,
            kind="initial" if kind == "initial" else "repair",
            candidate=candidate,
            provider=response.provider,
            model=response.model,
            finish_reason=response.finish_reason,
            gates=gates,
            passed=passed,
        )

    def _self_score_gate(self, candidate: GeneratedCandidate) -> QualityGate:
        confidence = min(candidate.relevance_score, candidate.accuracy_score)
        reasons: list[str] = []
        if candidate.relevance_score < self.self_score_threshold:
            reasons.append("low_relevance_self_score")
        if candidate.accuracy_score < self.self_score_threshold:
            reasons.append("low_accuracy_self_score")
        return QualityGate(
            gate="model_self_score",
            passed=not reasons,
            confidence=confidence,
            reasons=reasons,
        )

    def _post_audit_gate(self, audit: QualityGate) -> QualityGate:
        passed = audit.confidence >= self.post_audit_threshold
        return QualityGate(
            gate="post_audit_confidence",
            passed=passed,
            confidence=audit.confidence,
            reasons=[] if passed else ["below_post_audit_threshold"],
        )

    async def _answered(
        self,
        query: str,
        retrieval: RagRetrievalResult,
        eligible_citations: list[Citation],
        attempts: list[GenerationAttempt],
        candidate: GeneratedCandidate,
        *,
        repaired: bool,
    ) -> RagAnswerResult:
        used_indices = citation_indices(candidate.answer)
        selected = [citation for citation in eligible_citations if citation.index in used_indices]
        confidence = attempts[-1].gates[-1].confidence
        return await self._finalize(
            RagAnswerResult(
                query=query,
                status="answered",
                answer=candidate.answer,
                confidence=confidence,
                used_citation_indices=used_indices,
                citations=selected,
                retrieval=retrieval,
                attempts=attempts,
                repaired=repaired,
            )
        )

    async def _finalize(self, result: RagAnswerResult) -> RagAnswerResult:
        if self.store_records:
            result.record_id = await asyncio.to_thread(self.repository.save, result)
        return result

    def _context(self, citations: list[Citation]) -> str:
        return "\n\n".join(
            f"[{citation.index}] {citation.title}\n"
            f"{citation.snippet}\n"
            f"Source: {citation.source_uri}"
            for citation in citations
        )

