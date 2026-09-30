from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from enterprise_rag.api.dependencies import TaskFlowServiceDependency
from enterprise_rag.core.errors import ResourceNotFoundError
from enterprise_rag.taskflow.models import TaskSession

router = APIRouter()


@router.get("/{conversation_id}", response_model=TaskSession)
async def get_latest_task(
    conversation_id: str,
    service: TaskFlowServiceDependency,
) -> TaskSession:
    session = await run_in_threadpool(service.get_latest, conversation_id)
    if session is None:
        raise ResourceNotFoundError("task_session", conversation_id)
    return session
