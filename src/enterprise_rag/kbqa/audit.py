import re
from typing import ClassVar

from enterprise_rag.kbqa.models import GateResult, KnowledgeCandidate


class AnswerAuditor:
    _blocked_patterns: ClassVar[tuple[re.Pattern[str], ...]] = tuple(
        re.compile(pattern)
        for pattern in (
            r"保证赔付",
            r"一定赔偿",
            r"百分之百赔付",
            r"绝对不会",
        )
    )

    def audit(self, candidate: KnowledgeCandidate) -> GateResult:
        reasons: list[str] = []
        if not candidate.answer.strip():
            reasons.append("empty_answer")
        if any(pattern.search(candidate.answer) for pattern in self._blocked_patterns):
            reasons.append("risky_commitment")
        if not candidate.evidence:
            reasons.append("missing_evidence")
        confidence = candidate.confidence if not reasons else min(candidate.confidence, 0.5)
        return GateResult(
            gate="answer_audit",
            passed=not reasons,
            confidence=confidence,
            reasons=reasons,
        )
