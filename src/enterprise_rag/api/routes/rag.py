import asyncio
import json
from collections.abc import AsyncIterator, Mapping

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from enterprise_rag.api.dependencies import (
    AnswerEvaluatorDependency,
    AnswerGenerationServiceDependency,
    AnswerRecordRepositoryDependency,
    RagServiceDependency,
    RetrieverEvaluatorDependency,
)
from enterprise_rag.generation.models import (
    AnswerEvaluationCase,
    AnswerEvaluationResult,
    AnswerQualitySummary,
    RagAnswerResult,
)
from enterprise_rag.rag.models import (
    EvaluationCase,
    RagRetrievalResult,
    RetrievalEvaluationResult,
)

router = APIRouter()


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class EvaluationRequest(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1, max_length=1000)
    k: int = Field(default=10, ge=1, le=100)


class AnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class AnswerEvaluationRequest(BaseModel):
    cases: list[AnswerEvaluationCase] = Field(min_length=1, max_length=1000)


@router.post("/retrieve", response_model=RagRetrievalResult)
async def retrieve(
    request: RetrievalRequest,
    service: RagServiceDependency,
) -> RagRetrievalResult:
    return await run_in_threadpool(service.retrieve, request.query)


@router.post("/evaluate", response_model=RetrievalEvaluationResult)
async def evaluate(
    request: EvaluationRequest,
    evaluator: RetrieverEvaluatorDependency,
) -> RetrievalEvaluationResult:
    return await run_in_threadpool(evaluator.evaluate, request.cases, k=request.k)


@router.post("/evaluate/answers", response_model=AnswerEvaluationResult)
async def evaluate_answers(
    request: AnswerEvaluationRequest,
    evaluator: AnswerEvaluatorDependency,
) -> AnswerEvaluationResult:
    return await evaluator.evaluate(request.cases)


@router.post("/answer", response_model=RagAnswerResult)
async def answer(
    request: AnswerRequest,
    service: AnswerGenerationServiceDependency,
) -> RagAnswerResult:
    return await service.answer(request.query)


@router.post("/answer/stream")
async def stream_answer(
    request: AnswerRequest,
    service: AnswerGenerationServiceDependency,
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        result = await service.answer(request.query)
        metadata = {
            "status": result.status,
            "confidence": result.confidence,
            "citations": [citation.model_dump(mode="json") for citation in result.citations],
        }
        yield _sse("metadata", metadata)
        for start in range(0, len(result.answer), 24):
            yield _sse("answer", {"text": result.answer[start : start + 24]})
            await asyncio.sleep(0)
        yield _sse(
            "done",
            {
                "status": result.status,
                "repaired": result.repaired,
                "record_id": result.record_id,
            },
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/quality/summary", response_model=AnswerQualitySummary)
async def quality_summary(
    repository: AnswerRecordRepositoryDependency,
) -> AnswerQualitySummary:
    return await run_in_threadpool(repository.summary)


def _sse(event: str, payload: Mapping[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
