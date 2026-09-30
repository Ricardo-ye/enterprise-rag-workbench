from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SafetyDecision(StrEnum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


class IntentKind(StrEnum):
    TASK = "task"
    QA = "qa"
    UNKNOWN = "unknown"


class RouteTarget(StrEnum):
    REJECT = "reject"
    CHITCHAT = "chitchat"
    TASK_FLOW = "task_flow"
    KBQA = "kbqa"
    RAG = "rag"


class Audience(StrEnum):
    TO_C = "toc"
    TO_B = "tob"


class ActorType(StrEnum):
    UNKNOWN = "unknown"
    CONSUMER = "consumer"
    EMPLOYEE = "employee"
    PARTNER = "partner"
    BUSINESS = "business"


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ActiveTaskContext(BaseModel):
    intent: str = Field(min_length=1, max_length=100)
    collected_slots: dict[str, Any] = Field(default_factory=dict)


class RoutingContext(BaseModel):
    history: list[ConversationTurn] = Field(default_factory=list, max_length=20)
    active_task: ActiveTaskContext | None = None


class SafetyMatch(BaseModel):
    rule_id: str
    category: str
    decision: SafetyDecision


class SafetyAssessment(BaseModel):
    decision: SafetyDecision
    matches: list[SafetyMatch]


class Classification(BaseModel):
    name: str
    display_name: str
    confidence: float = Field(ge=0, le=1)
    matched_terms: list[str] = Field(default_factory=list)


class IntentClassification(Classification):
    kind: IntentKind
    domain: str
    required_slots: list[str] = Field(default_factory=list)
    inherited_from_context: bool = False
    source: Literal["keyword", "nearest_intent", "context", "none"] = "none"


class TraceStep(BaseModel):
    stage: str
    decision: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    details: dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    trace_id: str
    normalized_query: str
    safety: SafetyAssessment
    audience: Audience
    domain: Classification
    intent: IntentClassification
    is_follow_up: bool
    target: RouteTarget
    reason: str
    trace: list[TraceStep]
