from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class GenerationRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=32768)


class GenerationResponse(BaseModel):
    text: str
    provider: str
    model: str
    finish_reason: str | None = None


class ModelProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Generate one response for the supplied conversation."""

    async def close(self) -> None:
        """Release provider resources when the application shuts down."""
        return None
