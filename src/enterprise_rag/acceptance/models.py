from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AcceptanceCaseResult(BaseModel):
    name: str
    category: str
    passed: bool
    duration_ms: float = Field(ge=0)
    status_code: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AcceptanceReport(BaseModel):
    generated_at: datetime
    base_url: str
    status: Literal["passed", "failed"]
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    cases: list[AcceptanceCaseResult]
    known_boundaries: list[str]
