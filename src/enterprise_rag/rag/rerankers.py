import importlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any

from enterprise_rag.core.errors import ConfigurationError
from enterprise_rag.rag.models import FusedHit


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, hits: list[FusedHit]) -> list[FusedHit]:
        """Return hits ordered by relevance with rerank_score populated."""


class HeuristicReranker(Reranker):
    """Offline deterministic reranker for local development and tests."""

    def rerank(self, query: str, hits: list[FusedHit]) -> list[FusedHit]:
        if not hits:
            return []
        max_rrf = max(hit.rrf_score for hit in hits) or 1.0
        for hit in hits:
            overlap = query_coverage(query, f"{hit.title} {hit.content}")
            phrase_bonus = 1.0 if query.casefold() in hit.content.casefold() else 0.0
            normalized_rrf = hit.rrf_score / max_rrf
            route_bonus = min(len(hit.retrieval_routes) / 3.0, 1.0)
            # Do not turn a popular but unrelated document into high-quality
            # evidence merely because several retrievers returned it.  The
            # generation layer enforces a stricter coverage threshold too.
            if overlap == 0 and phrase_bonus == 0:
                hit.rerank_score = min(0.25, 0.15 * normalized_rrf + 0.10 * route_bonus)
            else:
                hit.rerank_score = min(
                    1.0,
                    0.70 * overlap
                    + 0.15 * normalized_rrf
                    + 0.10 * route_bonus
                    + 0.05 * phrase_bonus,
                )
            if _contains_query_echo(question=query, evidence=hit.content):
                # Example questions and FAQ-like headings are useful metadata,
                # but they are not answers.  They must not outrank the policy
                # clause that carries the actual rule.
                hit.rerank_score = min(hit.rerank_score, 0.25)
        return sorted(hits, key=lambda item: (-item.rerank_score, -item.rrf_score, item.id))


class CrossEncoderReranker(Reranker):
    """Optional sentence-transformers CrossEncoder adapter."""

    def __init__(self, model_name: str) -> None:
        try:
            module = importlib.import_module("sentence_transformers")
        except ImportError as exc:
            raise ConfigurationError(
                "Cross-encoder reranking requires the optional sentence-transformers package"
            ) from exc
        model_class: Any = module.CrossEncoder
        self.model: Any = model_class(model_name)

    def rerank(self, query: str, hits: list[FusedHit]) -> list[FusedHit]:
        if not hits:
            return []
        raw_scores: Any = self.model.predict([(query, hit.content) for hit in hits])
        for hit, raw_score in zip(hits, raw_scores, strict=True):
            hit.rerank_score = _sigmoid(float(raw_score))
        return sorted(hits, key=lambda item: (-item.rerank_score, -item.rrf_score, item.id))


def _terms(text: str) -> set[str]:
    lowered = text.casefold()
    latin = set(re.findall(r"[a-z0-9]+", lowered))
    chinese = {
        lowered[index : index + 2]
        for index in range(len(lowered) - 1)
        if "\u4e00" <= lowered[index] <= "\u9fff" and "\u4e00" <= lowered[index + 1] <= "\u9fff"
    }
    question_noise = {
        "什么",
        "是什",
        "策是",
        "怎么",
        "如何",
        "为什",
        "为何",
        "多少",
        "能否",
        "是否",
    }
    return latin | (chinese - question_noise)


def query_coverage(query: str, evidence: str) -> float:
    """Return how much of a query is explicitly supported by one evidence item."""
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    return len(query_terms & _terms(evidence)) / len(query_terms)


def _contains_query_echo(*, question: str, evidence: str) -> bool:
    normalized_question = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", question.casefold())
    normalized_evidence = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", evidence.casefold())
    return bool(
        normalized_question
        and normalized_question in normalized_evidence
        and ("?" in evidence or "？" in evidence)
    )


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)

