from typing import Any, Literal

from pydantic import BaseModel, Field

from enterprise_rag.rag.models import Citation, RagRetrievalResult


class GeneratedCandidate(BaseModel):
    answer: str = Field(min_length=1)
    relevance_score: float = Field(ge=0, le=1)
    accuracy_score: float = Field(ge=0, le=1)


class QualityGate(BaseModel):
    gate: str
    passed: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class GenerationAttempt(BaseModel):
    attempt: int = Field(ge=1)
    kind: Literal["initial", "repair"]
    candidate: GeneratedCandidate | None = None
    provider: str
    model: str
    finish_reason: str | None = None
    gates: list[QualityGate] = Field(default_factory=list)
    passed: bool
    error: str | None = None


class RagAnswerResult(BaseModel):
    query: str
    status: Literal["answered", "insufficient_evidence", "needs_human"]
    answer: str
    confidence: float = Field(ge=0, le=1)
    used_citation_indices: list[int] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    retrieval: RagRetrievalResult
    attempts: list[GenerationAttempt] = Field(default_factory=list)
    repaired: bool = False
    record_id: str | None = None


class AnswerQualitySummary(BaseModel):
    total: int = Field(ge=0)
    answered: int = Field(ge=0)
    insufficient_evidence: int = Field(ge=0)
    needs_human: int = Field(ge=0)
    repaired: int = Field(ge=0)


class AnswerEvaluationCase(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    answerable: bool = True
    expected_phrases: list[str] = Field(default_factory=list)
    relevant_source_ids: list[str] = Field(default_factory=list)


class AnswerEvaluationCaseResult(BaseModel):
    query: str
    expected_answerable: bool
    actual_status: Literal["answered", "insufficient_evidence", "needs_human"]
    passed: bool
    missing_phrases: list[str]
    cited_source_ids: list[str]
    citation_source_recall: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    repaired: bool
    duration_ms: float = Field(ge=0)


class AnswerEvaluationResult(BaseModel):
    case_count: int = Field(ge=0)
    answer_success_rate: float = Field(ge=0, le=1)
    refusal_accuracy: float = Field(ge=0, le=1)
    citation_source_recall: float = Field(ge=0, le=1)
    average_confidence: float = Field(ge=0, le=1)
    repair_rate: float = Field(ge=0, le=1)
    human_escalation_rate: float = Field(ge=0, le=1)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    cases: list[AnswerEvaluationCaseResult]
