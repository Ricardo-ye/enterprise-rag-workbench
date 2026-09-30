import re
from typing import ClassVar

from enterprise_rag.generation.models import GeneratedCandidate, QualityGate
from enterprise_rag.generation.parser import citation_indices
from enterprise_rag.rag.models import Citation


class GroundedAnswerAuditor:
    _blocked_patterns: ClassVar[tuple[re.Pattern[str], ...]] = tuple(
        re.compile(pattern)
        for pattern in (
            r"保证赔付",
            r"一定赔偿",
            r"百分之百赔付",
            r"保证通过",
            r"绝对不会",
            r"忽略(?:之前|以上|所有).*指令",
            r"(?:输出|泄露|显示).*(?:系统提示词|system prompt)",
        )
    )

    def __init__(self, *, min_grounding_coverage: float) -> None:
        self.min_grounding_coverage = min_grounding_coverage

    def audit(
        self,
        query: str,
        candidate: GeneratedCandidate,
        citations: list[Citation],
        *,
        finish_reason: str | None,
    ) -> QualityGate:
        reasons: list[str] = []
        details: dict[str, object] = {}
        citation_map = {citation.index: citation for citation in citations}
        used_indices = citation_indices(candidate.answer)
        invalid = [index for index in used_indices if index not in citation_map]
        if not used_indices:
            reasons.append("missing_citation")
        if invalid:
            reasons.append("invalid_citation")
            details["invalid_citation_indices"] = invalid

        if any(pattern.search(candidate.answer) for pattern in self._blocked_patterns):
            reasons.append("risky_commitment")
        if finish_reason in {"length", "max_tokens"}:
            reasons.append("possibly_truncated")
        if len(_strip_citations(candidate.answer).strip()) < 4:
            reasons.append("incomplete_answer")

        query_terms = _terms(query)
        answer_terms = _terms(_strip_citations(candidate.answer))
        relevance_overlap = len(query_terms & answer_terms) / max(len(query_terms), 1)
        details["query_overlap"] = round(relevance_overlap, 6)
        if not query_terms.intersection(answer_terms):
            reasons.append("answer_not_relevant")

        statement_coverages: list[float] = []
        for statement in _statements(candidate.answer):
            statement_indices = citation_indices(statement)
            if not statement_indices:
                reasons.append("uncited_statement")
                continue
            if any(index not in citation_map for index in statement_indices):
                continue
            if not _citation_at_end(statement):
                reasons.append("citation_not_at_statement_end")
            evidence = " ".join(citation_map[index].snippet for index in statement_indices)
            statement_text = _strip_citations(statement)
            statement_terms = _terms(statement_text)
            evidence_terms = _terms(evidence)
            coverage = len(statement_terms & evidence_terms) / max(len(statement_terms), 1)
            statement_coverages.append(coverage)
            if coverage < self.min_grounding_coverage:
                reasons.append("weak_evidence_support")
            unsupported_numbers = sorted(_numbers(statement_text) - _numbers(evidence))
            if unsupported_numbers:
                reasons.append("unsupported_numeric_claim")
                current_numbers = details.get("unsupported_numbers")
                accumulated = list(current_numbers) if isinstance(current_numbers, list) else []
                details["unsupported_numbers"] = accumulated + unsupported_numbers

        minimum_coverage = min(statement_coverages, default=0.0)
        details["minimum_statement_coverage"] = round(minimum_coverage, 6)
        unique_reasons = list(dict.fromkeys(reasons))
        confidence = (
            min(candidate.accuracy_score, candidate.relevance_score)
            if not unique_reasons
            else min(candidate.accuracy_score, candidate.relevance_score, 0.5)
        )
        return QualityGate(
            gate="answer_audit",
            passed=not unique_reasons,
            confidence=confidence,
            reasons=unique_reasons,
            details=details,
        )


def _statements(answer: str) -> list[str]:
    normalized = answer.replace("\r", "\n")
    return [
        value.strip()
        for value in re.split(r"(?<=[。！？!?；;])\s*|\n+", normalized)
        if value.strip()
    ]


def _citation_at_end(statement: str) -> bool:
    return bool(re.search(r"(?:\[\d+])+\s*[。！？!?；;]?$", statement))


def _strip_citations(text: str) -> str:
    return re.sub(r"\[\d+]", "", text)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?%?", text))


def _terms(text: str) -> set[str]:
    lowered = text.casefold()
    latin = set(re.findall(r"[a-z0-9]+", lowered))
    chinese = {
        lowered[index : index + 2]
        for index in range(len(lowered) - 1)
        if "\u4e00" <= lowered[index] <= "\u9fff" and "\u4e00" <= lowered[index + 1] <= "\u9fff"
    }
    return latin | chinese
