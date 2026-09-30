from concurrent.futures import ThreadPoolExecutor

from enterprise_rag.kbqa.audit import AnswerAuditor
from enterprise_rag.kbqa.models import GateResult, KbqaResult, KnowledgeCandidate
from enterprise_rag.kbqa.repository import KbqaRepository
from enterprise_rag.knowledge.embeddings import EmbeddingProvider
from enterprise_rag.routing.models import RouteTarget


class KbqaService:
    def __init__(
        self,
        *,
        repository: KbqaRepository,
        embedding_provider: EmbeddingProvider,
        auditor: AnswerAuditor,
        first_gate_threshold: float,
        second_gate_threshold: float,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.auditor = auditor
        self.first_gate_threshold = first_gate_threshold
        self.second_gate_threshold = second_gate_threshold

    def answer(self, query: str) -> KbqaResult:
        exact = self.repository.exact_faq(query)
        if exact:
            return KbqaResult(
                status="answered",
                path="faq_exact",
                target=RouteTarget.KBQA,
                answer=exact.answer,
                direct=True,
                candidate=exact,
                gates=[],
            )

        query_embedding = self.embedding_provider.embed([query])[0]
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="kbqa") as executor:
            faq_future = executor.submit(
                self.repository.faq_recall,
                query,
                query_embedding,
                limit=5,
            )
            kg_future = executor.submit(self.repository.kg_query, query, limit=5)
            faq_candidates = faq_future.result()
            kg_candidates = kg_future.result()

        candidates = [*faq_candidates, *kg_candidates]
        if not candidates:
            return self._fallback(None, [], "no_candidate")
        candidate = max(candidates, key=lambda item: item.confidence)
        first_gate = GateResult(
            gate="candidate_confidence",
            passed=candidate.confidence >= self.first_gate_threshold,
            confidence=candidate.confidence,
            reasons=(
                []
                if candidate.confidence >= self.first_gate_threshold
                else ["below_first_gate_threshold"]
            ),
        )
        if not first_gate.passed:
            return self._fallback(candidate, [first_gate], "first_gate_failed")

        audit = self.auditor.audit(candidate)
        if not audit.passed:
            return self._fallback(candidate, [first_gate, audit], "answer_audit_failed")

        second_gate = GateResult(
            gate="post_audit_confidence",
            passed=audit.confidence >= self.second_gate_threshold,
            confidence=audit.confidence,
            reasons=(
                []
                if audit.confidence >= self.second_gate_threshold
                else ["below_second_gate_threshold"]
            ),
        )
        gates = [first_gate, audit, second_gate]
        if not second_gate.passed:
            return self._fallback(candidate, gates, "second_gate_failed")
        return KbqaResult(
            status="answered",
            path="faq_recall" if candidate.source_type == "faq" else "kg",
            target=RouteTarget.KBQA,
            answer=candidate.answer,
            direct=False,
            candidate=candidate,
            gates=gates,
        )

    def _fallback(
        self,
        candidate: KnowledgeCandidate | None,
        gates: list[GateResult],
        reason: str,
    ) -> KbqaResult:
        if gates:
            gates[-1].reasons.append(reason)
        else:
            gates = [
                GateResult(
                    gate="candidate_confidence",
                    passed=False,
                    confidence=0.0,
                    reasons=[reason],
                )
            ]
        return KbqaResult(
            status="fallback",
            path="fallback",
            target=RouteTarget.RAG,
            answer=None,
            direct=False,
            candidate=candidate,
            gates=gates,
        )
