from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskStage(StrEnum):
    NEEDS_INPUT = "needs_input"
    ACTION_COMPLETED = "action_completed"
    CANCELLED = "cancelled"


class TaskSession(BaseModel):
    id: str
    conversation_id: str
    intent: str
    status: TaskStatus
    slots: dict[str, Any] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    action_result: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class ActionResult(BaseModel):
    success: bool
    action: str
    reference_id: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskFlowResult(BaseModel):
    stage: TaskStage
    session: TaskSession
    message: str
    requested_slot: str | None = None
    action: ActionResult | None = None
