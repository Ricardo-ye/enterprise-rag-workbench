from typing import Any, Literal

from pydantic import BaseModel, Field

from enterprise_rag.routing.models import RouteTarget


class KnowledgeCandidate(BaseModel):
    source_type: Literal["faq", "kg"]
    source_id: str
    answer: str
    confidence: float = Field(ge=0, le=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class GateResult(BaseModel):
    gate: str
    passed: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class KbqaResult(BaseModel):
    status: Literal["answered", "fallback"]
    path: Literal["faq_exact", "faq_recall", "kg", "fallback"]
    target: RouteTarget
    answer: str | None = None
    direct: bool = False
    candidate: KnowledgeCandidate | None = None
    gates: list[GateResult] = Field(default_factory=list)


class KgTripleInput(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    predicate: str = Field(min_length=1, max_length=200)
    object: str = Field(min_length=1, max_length=4000)
    subject_aliases: list[str] = Field(default_factory=list, max_length=50)
    predicate_aliases: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KgImportSummary(BaseModel):
    created: int
    updated: int
