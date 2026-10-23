from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RetrievalRoute(StrEnum):
    SEMANTIC = "semantic"
    LEXICAL = "lexical"
    WEB = "web"
    KG = "kg"
    FAQ = "faq"


class RetrievalHit(BaseModel):
    id: str
    route: RetrievalRoute
    source_type: str
    source_id: str
    content: str
    score: float
    title: str
    source_uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FusedHit(BaseModel):
    id: str
    source_type: str
    source_id: str
    content: str
    title: str
    source_uri: str
    retrieval_routes: list[RetrievalRoute]
    route_ranks: dict[str, int]
    route_scores: dict[str, float]
    rrf_score: float
    rerank_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RouteExecution(BaseModel):
    route: RetrievalRoute
    status: Literal["ok", "empty", "timeout", "error", "circuit_open", "skipped"]
    duration_ms: float = Field(ge=0)
    hit_count: int = Field(ge=0)
    error: str | None = None


class Citation(BaseModel):
    index: int = Field(ge=1)
    source_type: str
    source_id: str
    title: str
    source_uri: str
    snippet: str
    score: float
    # Coverage of the user query in this specific piece of evidence.  It is
    # deliberately separate from score: an RRF score measures rank agreement,
    # not whether the evidence actually answers the current question.
    query_coverage: float = Field(default=1.0, ge=0, le=1)
    retrieval_routes: list[RetrievalRoute]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagRetrievalResult(BaseModel):
    query: str
    hits: list[FusedHit]
    citations: list[Citation]
    context: str
    routes: list[RouteExecution]
    duration_ms: float = Field(ge=0)


class EvaluationCase(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    relevant_source_ids: list[str] = Field(min_length=1)


class EvaluationCaseResult(BaseModel):
    query: str
    retrieved_source_ids: list[str]
    recall_at_k: float = Field(ge=0, le=1)
    reciprocal_rank: float = Field(ge=0, le=1)
    ndcg_at_k: float = Field(ge=0, le=1)


class RetrievalEvaluationResult(BaseModel):
    k: int
    case_count: int
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    cases: list[EvaluationCaseResult]

