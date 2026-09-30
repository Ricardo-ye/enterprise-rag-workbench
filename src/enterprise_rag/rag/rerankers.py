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
        query_terms = _terms(query)
        max_rrf = max(hit.rrf_score for hit in hits) or 1.0
        for hit in hits:
            text_terms = _terms(f"{hit.title} {hit.content}")
            overlap = len(query_terms & text_terms) / max(len(query_terms), 1)
            phrase_bonus = 1.0 if query.casefold() in hit.content.casefold() else 0.0
            normalized_rrf = hit.rrf_score / max_rrf
            route_bonus = min(len(hit.retrieval_routes) / 3.0, 1.0)
            hit.rerank_score = min(
                1.0,
                0.55 * overlap + 0.30 * normalized_rrf + 0.10 * route_bonus + 0.05 * phrase_bonus,
            )
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
    return latin | chinese


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)
