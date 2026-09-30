from typing import Literal

from pydantic import BaseModel, Field


class SloCheck(BaseModel):
    name: str
    target: float
    actual: float | None = None
    unit: Literal["ratio", "milliseconds"]
    passed: bool | None = None


class SloSnapshot(BaseModel):
    status: Literal["healthy", "violated", "no_data"]
    window: str = "process_lifetime"
    request_samples: int = Field(ge=0)
    answer_samples: int = Field(ge=0)
    checks: list[SloCheck]
