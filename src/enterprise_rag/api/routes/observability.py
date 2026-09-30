from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from enterprise_rag.core.config import Settings
from enterprise_rag.observability.metrics import MetricsRegistry
from enterprise_rag.observability.models import SloSnapshot

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    registry = cast(MetricsRegistry, request.app.state.metrics_registry)
    return PlainTextResponse(
        registry.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/api/v1/observability/slo", response_model=SloSnapshot)
async def slo(request: Request) -> SloSnapshot:
    registry = cast(MetricsRegistry, request.app.state.metrics_registry)
    settings = cast(Settings, request.app.state.settings)
    return registry.slo_snapshot(
        availability_target=settings.slo_availability_target,
        p95_latency_ms_target=settings.slo_p95_latency_ms,
        answer_success_target=settings.slo_answer_success_target,
    )
