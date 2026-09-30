import hashlib
from pathlib import Path
from typing import Any

from enterprise_rag.core.errors import (
    KnowledgeValidationError,
    ResourceNotFoundError,
)
from enterprise_rag.knowledge.chunking import StructureAwareChunker
from enterprise_rag.knowledge.embeddings import EmbeddingProvider
from enterprise_rag.knowledge.models import (
    ChunkCandidate,
    DocumentRecord,
    FaqImportSummary,
    FaqItem,
    IngestionOutcome,
    ParsedDocument,
    SearchHit,
)
from enterprise_rag.knowledge.parsers import DocumentParser
from enterprise_rag.knowledge.repository import KnowledgeRepository


class KnowledgeService:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        parser: DocumentParser,
        chunker: StructureAwareChunker,
        embedding_provider: EmbeddingProvider,
        max_upload_bytes: int,
    ) -> None:
        self.repository = repository
        self.parser = parser
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.max_upload_bytes = max_upload_bytes

    def ingest_bytes(
        self,
        *,
        content: bytes,
        filename: str,
        source_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionOutcome:
        if not content:
            raise KnowledgeValidationError("Uploaded document is empty")
        if len(content) > self.max_upload_bytes:
            raise KnowledgeValidationError(
                "Uploaded document exceeds the size limit",
                status_code=413,
            )
        effective_source = source_uri or f"upload://{filename}"
        content_hash = hashlib.sha256(content).hexdigest()

        existing = self.repository.get_document_by_source(effective_source)
        if existing and existing.status == "active" and existing.content_hash == content_hash:
            return IngestionOutcome(action="unchanged", document=existing)

        duplicate = self.repository.get_active_document_by_hash(
            content_hash,
            exclude_source=effective_source,
        )
        if duplicate:
            return IngestionOutcome(action="duplicate", document=duplicate)

        parsed = self.parser.parse(content, filename)
        combined_metadata = {**parsed.metadata, **(metadata or {}), "filename": filename}
        parsed = ParsedDocument(
            text=parsed.text,
            title=parsed.title,
            mime_type=parsed.mime_type,
            metadata=combined_metadata,
        )
        chunks = self._build_chunks(parsed)
        document, created = self.repository.save_document_version(
            source_uri=effective_source,
            title=parsed.title,
            mime_type=parsed.mime_type,
            content_hash=content_hash,
            parsed_text=parsed.text,
            metadata=combined_metadata,
            chunks=chunks,
        )
        return IngestionOutcome(
            action="created" if created else "updated",
            document=document,
        )

    def ingest_file(
        self,
        path: Path,
        *,
        source_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionOutcome:
        resolved = path.resolve(strict=True)
        return self.ingest_bytes(
            content=resolved.read_bytes(),
            filename=resolved.name,
            source_uri=source_uri or resolved.as_uri(),
            metadata=metadata,
        )

    def list_documents(self) -> list[DocumentRecord]:
        return self.repository.list_documents()

    def delete_document(self, document_id: str) -> None:
        if not self.repository.soft_delete_document(document_id):
            raise ResourceNotFoundError("document", document_id)

    def import_faqs(self, items: list[FaqItem]) -> FaqImportSummary:
        if not items:
            raise KnowledgeValidationError("At least one FAQ item is required")
        embeddings = self.embedding_provider.embed([item.question for item in items])
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for item, embedding in zip(items, embeddings, strict=True):
            content_hash = hashlib.sha256(
                f"{item.question.strip()}\0{item.answer.strip()}".encode()
            ).hexdigest()
            action = self.repository.upsert_faq(item, embedding, content_hash)
            counts[action] += 1
        return FaqImportSummary(**counts)

    def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[list[SearchHit], list[SearchHit]]:
        normalized = query.strip()
        if not normalized:
            raise KnowledgeValidationError("Search query must not be empty")
        query_embedding = self.embedding_provider.embed([normalized])[0]
        return (
            self.repository.lexical_search(normalized, limit),
            self.repository.vector_search(query_embedding, limit),
        )

    def rebuild_indexes(self) -> dict[str, int]:
        versions = self.repository.list_current_versions()
        chunk_count = 0
        for version in versions:
            parsed = ParsedDocument(
                text=version.parsed_text,
                title=version.title,
                mime_type=version.mime_type,
                metadata=version.metadata,
            )
            chunks = self._build_chunks(parsed)
            self.repository.replace_version_chunks(
                document_id=version.document_id,
                version_id=version.version_id,
                chunks=chunks,
            )
            chunk_count += len(chunks)
        faq_rows = self.repository.list_active_faq_questions()
        if faq_rows:
            faq_vectors = self.embedding_provider.embed([question for _, question in faq_rows])
            self.repository.replace_faq_embeddings(
                [
                    (faq_id, embedding)
                    for (faq_id, _), embedding in zip(faq_rows, faq_vectors, strict=True)
                ]
            )
        self.repository.rebuild_fts_indexes()
        return {
            "documents": len(versions),
            "chunks": chunk_count,
            "faqs": len(faq_rows),
        }

    def _build_chunks(self, parsed: ParsedDocument) -> list[ChunkCandidate]:
        raw_chunks = self.chunker.chunk(parsed)
        if not raw_chunks:
            raise KnowledgeValidationError("Document produced no indexable chunks")
        embeddings = self.embedding_provider.embed([chunk.content for chunk in raw_chunks])
        return [
            ChunkCandidate(
                ordinal=chunk.ordinal,
                content=chunk.content,
                content_hash=chunk.content_hash,
                token_count=chunk.token_count,
                metadata=chunk.metadata,
                embedding=embedding,
            )
            for chunk, embedding in zip(raw_chunks, embeddings, strict=True)
        ]
