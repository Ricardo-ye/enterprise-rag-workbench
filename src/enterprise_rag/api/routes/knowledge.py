import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from enterprise_rag.api.dependencies import KnowledgeServiceDependency
from enterprise_rag.core.errors import KnowledgeValidationError
from enterprise_rag.knowledge.models import FaqItem

router = APIRouter()


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_uri: str
    title: str
    mime_type: str
    content_hash: str
    current_version: int
    status: str
    chunk_count: int
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


class IngestionResponse(BaseModel):
    action: Literal["created", "updated", "unchanged", "duplicate"]
    document: DocumentResponse


class FaqRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=20000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


class FaqImportRequest(BaseModel):
    items: list[FaqRequest] = Field(min_length=1, max_length=1000)


class FaqImportResponse(BaseModel):
    created: int
    updated: int
    unchanged: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=50)


class SearchHitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: Literal["document", "faq"]
    source_id: str
    content: str
    score: float
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    lexical: list[SearchHitResponse]
    vector: list[SearchHitResponse]


class RebuildResponse(BaseModel):
    status: str
    documents: int
    chunks: int
    faqs: int


@router.post("/documents/ingest", response_model=IngestionResponse)
async def ingest_document(
    service: KnowledgeServiceDependency,
    file: Annotated[UploadFile, File(description="Markdown, UTF-8 text, or PDF")],
    source_uri: Annotated[str | None, Form()] = None,
    metadata_json: Annotated[str, Form()] = "{}",
) -> IngestionResponse:
    content = await file.read(service.max_upload_bytes + 1)
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise KnowledgeValidationError("metadata_json must be valid JSON") from exc
    if not isinstance(metadata, dict):
        raise KnowledgeValidationError("metadata_json must contain a JSON object")
    filename = file.filename or "document.txt"
    outcome = await run_in_threadpool(
        service.ingest_bytes,
        content=content,
        filename=filename,
        source_uri=source_uri,
        metadata=metadata,
    )
    return IngestionResponse(
        action=outcome.action,
        document=DocumentResponse.model_validate(outcome.document),
    )


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(service: KnowledgeServiceDependency) -> list[DocumentResponse]:
    documents = await run_in_threadpool(service.list_documents)
    return [DocumentResponse.model_validate(document) for document in documents]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    service: KnowledgeServiceDependency,
) -> Response:
    await run_in_threadpool(service.delete_document, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/faqs/import", response_model=FaqImportResponse)
async def import_faqs(
    request: FaqImportRequest,
    service: KnowledgeServiceDependency,
) -> FaqImportResponse:
    items = [
        FaqItem(
            question=item.question,
            answer=item.answer,
            metadata=item.metadata,
            approved=item.approved,
        )
        for item in request.items
    ]
    summary = await run_in_threadpool(service.import_faqs, items)
    return FaqImportResponse(
        created=summary.created,
        updated=summary.updated,
        unchanged=summary.unchanged,
    )


@router.post("/search", response_model=SearchResponse)
async def search_indexes(
    request: SearchRequest,
    service: KnowledgeServiceDependency,
) -> SearchResponse:
    lexical, vector = await run_in_threadpool(
        service.search,
        request.query,
        limit=request.limit,
    )
    return SearchResponse(
        query=request.query,
        lexical=[SearchHitResponse.model_validate(hit) for hit in lexical],
        vector=[SearchHitResponse.model_validate(hit) for hit in vector],
    )


@router.post("/indexes/rebuild", response_model=RebuildResponse)
async def rebuild_indexes(service: KnowledgeServiceDependency) -> RebuildResponse:
    result = await run_in_threadpool(service.rebuild_indexes)
    return RebuildResponse(status="ok", **result)
