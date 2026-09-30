from fastapi import APIRouter

from enterprise_rag.api.routes import (
    assistant,
    health,
    kbqa,
    knowledge,
    observability,
    rag,
    routing,
    system,
    tasks,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router, prefix="/api/v1/system", tags=["system"])
api_router.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"])
api_router.include_router(routing.router, prefix="/api/v1/routing", tags=["routing"])
api_router.include_router(assistant.router, prefix="/api/v1/assistant", tags=["assistant"])
api_router.include_router(kbqa.router, prefix="/api/v1/kbqa", tags=["kbqa"])
api_router.include_router(rag.router, prefix="/api/v1/rag", tags=["rag"])
api_router.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
api_router.include_router(observability.router)
