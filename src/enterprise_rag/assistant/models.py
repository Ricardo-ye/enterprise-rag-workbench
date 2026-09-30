from typing import Any, Literal

from pydantic import BaseModel, Field

from enterprise_rag.generation.models import RagAnswerResult
from enterprise_rag.kbqa.models import KbqaResult
from enterprise_rag.rag.models import RagRetrievalResult
from enterprise_rag.routing.models import RoutingDecision
from enterprise_rag.taskflow.models import TaskFlowResult


class AssistantResult(BaseModel):
    conversation_id: str
    status: Literal[
        "answered",
        "needs_input",
        "action_completed",
        "cancelled",
        "handoff",
        "insufficient_evidence",
        "needs_human",
        "rejected",
    ]
    answer: str
    route: RoutingDecision
    task: TaskFlowResult | None = None
    kbqa: KbqaResult | None = None
    retrieval: RagRetrievalResult | None = None
    generation: RagAnswerResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
