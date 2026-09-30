from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    text: str
    title: str
    mime_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkCandidate:
    ordinal: int
    content: str
    content_hash: str
    token_count: int
    metadata: dict[str, Any]
    embedding: list[float]


@dataclass(frozen=True, slots=True)
class DocumentRecord:
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


@dataclass(frozen=True, slots=True)
class CurrentDocumentVersion:
    document_id: str
    version_id: str
    version: int
    source_uri: str
    title: str
    mime_type: str
    parsed_text: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    action: Literal["created", "updated", "unchanged", "duplicate"]
    document: DocumentRecord


@dataclass(frozen=True, slots=True)
class FaqItem:
    question: str
    answer: str
    metadata: dict[str, Any] = field(default_factory=dict)
    approved: bool = False


@dataclass(frozen=True, slots=True)
class FaqImportSummary:
    created: int
    updated: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: str
    source_type: Literal["document", "faq"]
    source_id: str
    content: str
    score: float
    metadata: dict[str, Any]
