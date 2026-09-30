import asyncio

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from enterprise_rag import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    model_provider: str | None = None


class ReadinessResponse(HealthResponse):
    components: dict[str, str]


@router.get("/health", response_model=HealthResponse)
@router.get("/health/live", response_model=HealthResponse)
async def live(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    settings = request.app.state.settings
    provider = request.app.state.model_provider
    readiness = await asyncio.to_thread(request.app.state.readiness_service.check)
    if not readiness.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if readiness.ready else "not_ready",
        service=settings.service_name,
        version=__version__,
        environment=settings.environment,
        model_provider=provider.name,
        components=readiness.components,
    )
