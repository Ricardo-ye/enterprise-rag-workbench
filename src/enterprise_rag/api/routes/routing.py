from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from enterprise_rag.api.dependencies import RoutingServiceDependency
from enterprise_rag.routing.models import (
    ActorType,
    RoutingContext,
    RoutingDecision,
)

router = APIRouter()


class RoutingRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    actor_type: ActorType = ActorType.UNKNOWN
    context: RoutingContext = Field(default_factory=RoutingContext)


@router.post("/route", response_model=RoutingDecision)
async def route_query(
    request: RoutingRequest,
    service: RoutingServiceDependency,
) -> RoutingDecision:
    return service.route(
        request.query,
        actor_type=request.actor_type,
        history=request.context.history,
        active_task=request.context.active_task,
    )


@router.get("/catalog", response_model=dict[str, Any])
async def routing_catalog(service: RoutingServiceDependency) -> dict[str, Any]:
    return service.catalog()
