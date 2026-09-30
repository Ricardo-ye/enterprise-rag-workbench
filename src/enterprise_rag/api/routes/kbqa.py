from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from enterprise_rag.api.dependencies import KbqaRepositoryDependency, KbqaServiceDependency
from enterprise_rag.kbqa.models import KbqaResult, KgImportSummary, KgTripleInput

router = APIRouter()


class KbqaRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class KgImportRequest(BaseModel):
    triples: list[KgTripleInput] = Field(min_length=1, max_length=1000)


@router.post("/query", response_model=KbqaResult)
async def query_kbqa(
    request: KbqaRequest,
    service: KbqaServiceDependency,
) -> KbqaResult:
    return await run_in_threadpool(service.answer, request.query)


@router.post("/kg/triples/import", response_model=KgImportSummary)
async def import_kg_triples(
    request: KgImportRequest,
    repository: KbqaRepositoryDependency,
) -> KgImportSummary:
    return await run_in_threadpool(repository.import_triples, request.triples)
