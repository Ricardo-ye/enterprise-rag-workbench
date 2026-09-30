from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from enterprise_rag.api.dependencies import AssistantServiceDependency
from enterprise_rag.assistant.models import AssistantResult
from enterprise_rag.routing.models import ActorType, ConversationTurn

router = APIRouter()


class AssistantRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=200)
    actor_type: ActorType = ActorType.UNKNOWN
    history: list[ConversationTurn] = Field(default_factory=list, max_length=20)
    provided_slots: dict[str, Any] = Field(default_factory=dict)


@router.post("/respond", response_model=AssistantResult)
async def respond(
    request: AssistantRequest,
    service: AssistantServiceDependency,
) -> AssistantResult:
    return await service.respond(
        request.query,
        conversation_id=request.conversation_id,
        actor_type=request.actor_type,
        history=request.history,
        provided_slots=request.provided_slots,
    )
