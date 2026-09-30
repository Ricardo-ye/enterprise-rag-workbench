from fastapi import APIRouter
from pydantic import BaseModel, Field

from enterprise_rag.api.dependencies import ModelProviderDependency
from enterprise_rag.providers.base import ChatMessage, GenerationRequest

router = APIRouter()


class ModelCheckRequest(BaseModel):
    prompt: str = Field(default="ping", min_length=1, max_length=500)


class ModelCheckResponse(BaseModel):
    status: str
    provider: str
    model: str
    response: str


@router.post("/model/check", response_model=ModelCheckResponse)
async def check_model(
    payload: ModelCheckRequest,
    provider: ModelProviderDependency,
) -> ModelCheckResponse:
    result = await provider.generate(
        GenerationRequest(messages=[ChatMessage(role="user", content=payload.prompt)])
    )
    return ModelCheckResponse(
        status="ok",
        provider=result.provider,
        model=result.model,
        response=result.text,
    )
