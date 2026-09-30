from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GeneralizationCase(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    input: dict[str, Any]
    expected: dict[str, Any]
    criterion: str = Field(min_length=1)


class GeneralizationGroup(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    cases: list[GeneralizationCase] = Field(min_length=1)


class GeneralizationDataset(BaseModel):
    version: int = Field(ge=1)
    description: str
    groups: list[GeneralizationGroup] = Field(min_length=1)


class GeneralizationCaseResult(BaseModel):
    id: str
    name: str
    scenario: str
    passed: bool
    duration_ms: float = Field(ge=0)
    input: dict[str, Any]
    expected: dict[str, Any]
    criterion: str
    actual: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class GeneralizationGroupResult(BaseModel):
    id: str
    name: str
    purpose: str
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    cases: list[GeneralizationCaseResult]


class GeneralizationReport(BaseModel):
    generated_at: datetime
    base_url: str
    status: Literal["passed", "needs_attention"]
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    duration_ms: float = Field(ge=0)
    setup: list[dict[str, Any]]
    groups: list[GeneralizationGroupResult]
    limitations: list[str]
    known_boundaries: list[str]
