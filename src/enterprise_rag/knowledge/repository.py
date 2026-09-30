import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from enterprise_rag.knowledge.embeddings import (
    cosine_similarity,
    pack_embedding,
    unpack_embedding,
)
from enterprise_rag.knowledge.models import (
    ChunkCandidate,
    CurrentDocumentVersion,
    DocumentRecord,
    FaqItem,
    SearchHit,
)
from enterprise_rag.knowledge.text import fts_query, fts_text, normalize_faq_question
from enterprise_rag.storage.sqlite import SQLiteDatabase, coerce_sqlite_database


class KnowledgeRepository:
    def __init__(self, database_path: Path | SQLiteDatabase) -> None:
        self.database = coerce_sqlite_database(database_path)
        self.database_path = self.database.path

    def initialize(self) -> None:
        self.database.initialize()
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    source_uri TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    current_version INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'deleted')),
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_content_hash
                    ON documents(content_hash, status);

                CREATE TABLE IF NOT EXISTS document_versions (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id),
                    version INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    parsed_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(document_id, version)
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id),
                    version_id TEXT NOT NULL REFERENCES document_versions(id),
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(version_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_active ON chunks(active, document_id);

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    search_text,
                    tokenize='unicode61'
                );

                CREATE TABLE IF NOT EXISTS faqs (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    question_normalized TEXT NOT NULL UNIQUE,
                    answer TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    approved INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN ('active', 'deleted')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS faqs_fts USING fts5(
                    faq_id UNINDEXED,
                    search_text,
                    tokenize='unicode61'
                );
                """
            )
            self._ensure_column(
                connection,
                table="faqs",
                column="approved",
                definition="INTEGER NOT NULL DEFAULT 0",
            )

    def get_document_by_source(self, source_uri: str) -> DocumentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                self._document_select() + " WHERE d.source_uri = ?",
                (source_uri,),
            ).fetchone()
        return self._document_from_row(row) if row else None

    def get_active_document_by_hash(
        self,
        content_hash: str,
        *,
        exclude_source: str | None = None,
    ) -> DocumentRecord | None:
        parameters: list[Any] = [content_hash]
        where = " WHERE d.content_hash = ? AND d.status = 'active'"
        if exclude_source is not None:
            where += " AND d.source_uri != ?"
            parameters.append(exclude_source)
        with self._connect() as connection:
            row = connection.execute(
                self._document_select() + where + " LIMIT 1",
                parameters,
            ).fetchone()
        return self._document_from_row(row) if row else None

    def save_document_version(
        self,
        *,
        source_uri: str,
        title: str,
        mime_type: str,
        content_hash: str,
        parsed_text: str,
        metadata: dict[str, Any],
        chunks: list[ChunkCandidate],
    ) -> tuple[DocumentRecord, bool]:
        now = self._now()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT id, current_version, created_at FROM documents WHERE source_uri = ?",
                (source_uri,),
            ).fetchone()
            created = current is None
            if current is None:
                document_id = uuid4().hex
                version = 1
                connection.execute(
                    """
                    INSERT INTO documents (
                        id, source_uri, title, mime_type, content_hash, current_version,
                        status, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (
                        document_id,
                        source_uri,
                        title,
                        mime_type,
                        content_hash,
                        version,
                        self._json(metadata),
                        now,
                        now,
                    ),
                )
            else:
                document_id = str(current["id"])
                version = int(current["current_version"]) + 1
                connection.execute(
                    "UPDATE chunks SET active = 0 WHERE document_id = ?",
                    (document_id,),
                )
                connection.execute(
                    """
                    UPDATE documents
                    SET title = ?, mime_type = ?, content_hash = ?, current_version = ?,
                        status = 'active', metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        mime_type,
                        content_hash,
                        version,
                        self._json(metadata),
                        now,
                        document_id,
                    ),
                )

            version_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO document_versions (
                    id, document_id, version, content_hash, parsed_text, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    document_id,
                    version,
                    content_hash,
                    parsed_text,
                    self._json(metadata),
                    now,
                ),
            )
            self._insert_chunks(connection, document_id, version_id, chunks, now)
            row = connection.execute(
                self._document_select() + " WHERE d.id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Document disappeared after insertion")
        return self._document_from_row(row), created

    def list_documents(self) -> list[DocumentRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                self._document_select() + " ORDER BY d.updated_at DESC"
            ).fetchall()
        return [self._document_from_row(row) for row in rows]

    def soft_delete_document(self, document_id: str) -> bool:
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE documents SET status = 'deleted', updated_at = ? WHERE id = ?",
                (now, document_id),
            )
            connection.execute(
                "UPDATE chunks SET active = 0 WHERE document_id = ?",
                (document_id,),
            )
        return cursor.rowcount > 0

    def list_current_versions(self) -> list[CurrentDocumentVersion]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT d.id AS document_id, v.id AS version_id, v.version, d.source_uri,
                       d.title, d.mime_type, v.parsed_text, v.metadata_json
                FROM documents d
                JOIN document_versions v
                  ON v.document_id = d.id AND v.version = d.current_version
                WHERE d.status = 'active'
                ORDER BY d.id
                """
            ).fetchall()
        return [
            CurrentDocumentVersion(
                document_id=str(row["document_id"]),
                version_id=str(row["version_id"]),
                version=int(row["version"]),
                source_uri=str(row["source_uri"]),
                title=str(row["title"]),
                mime_type=str(row["mime_type"]),
                parsed_text=str(row["parsed_text"]),
                metadata=self._load_json(str(row["metadata_json"])),
            )
            for row in rows
        ]

    def replace_version_chunks(
        self,
        *,
        document_id: str,
        version_id: str,
        chunks: list[ChunkCandidate],
    ) -> None:
        with self._connect() as connection:
            old_ids = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM chunks WHERE version_id = ?", (version_id,)
                ).fetchall()
            ]
            for chunk_id in old_ids:
                connection.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
            connection.execute("DELETE FROM chunks WHERE version_id = ?", (version_id,))
            self._insert_chunks(connection, document_id, version_id, chunks, self._now())

    def upsert_faq(self, item: FaqItem, embedding: list[float], content_hash: str) -> str:
        normalized_question = normalize_faq_question(item.question)
        now = self._now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, content_hash, approved FROM faqs WHERE question_normalized = ?",
                (normalized_question,),
            ).fetchone()
            if (
                existing
                and str(existing["content_hash"]) == content_hash
                and bool(existing["approved"]) == item.approved
            ):
                return "unchanged"
            if existing:
                faq_id = str(existing["id"])
                connection.execute("DELETE FROM faqs_fts WHERE faq_id = ?", (faq_id,))
                connection.execute(
                    """
                    UPDATE faqs
                    SET question = ?, answer = ?, content_hash = ?, metadata_json = ?,
                        embedding = ?, embedding_dimensions = ?, approved = ?,
                        status = 'active', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        item.question,
                        item.answer,
                        content_hash,
                        self._json(item.metadata),
                        pack_embedding(embedding),
                        len(embedding),
                        int(item.approved),
                        now,
                        faq_id,
                    ),
                )
                action = "updated"
            else:
                faq_id = uuid4().hex
                connection.execute(
                    """
                    INSERT INTO faqs (
                        id, question, question_normalized, answer, content_hash, metadata_json,
                        embedding, embedding_dimensions, approved, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        faq_id,
                        item.question,
                        normalized_question,
                        item.answer,
                        content_hash,
                        self._json(item.metadata),
                        pack_embedding(embedding),
                        len(embedding),
                        int(item.approved),
                        now,
                        now,
                    ),
                )
                action = "created"
            connection.execute(
                "INSERT INTO faqs_fts (faq_id, search_text) VALUES (?, ?)",
                (faq_id, fts_text(f"{item.question} {item.answer}")),
            )
        return action

    def lexical_search(self, query: str, limit: int) -> list[SearchHit]:
        match_query = fts_query(query)
        if not match_query:
            return []
        hits: list[SearchHit] = []
        with self._connect() as connection:
            chunk_rows = connection.execute(
                """
                SELECT c.id, c.document_id AS source_id, c.content, c.metadata_json,
                       c.ordinal, d.source_uri, d.title, bm25(chunks_fts) AS rank
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.chunk_id
                JOIN documents d ON d.id = c.document_id
                WHERE chunks_fts MATCH ? AND c.active = 1 AND d.status = 'active'
                ORDER BY rank
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()
            faq_rows = connection.execute(
                """
                SELECT f.id, f.question, f.answer, f.metadata_json, bm25(faqs_fts) AS rank
                FROM faqs_fts
                JOIN faqs f ON f.id = faqs_fts.faq_id
                WHERE faqs_fts MATCH ? AND f.status = 'active'
                ORDER BY rank
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()

        for row in chunk_rows:
            metadata = self._load_json(str(row["metadata_json"]))
            metadata.update(
                {
                    "source_uri": str(row["source_uri"]),
                    "title": str(row["title"]),
                    "ordinal": int(row["ordinal"]),
                }
            )
            hits.append(
                SearchHit(
                    id=str(row["id"]),
                    source_type="document",
                    source_id=str(row["source_id"]),
                    content=str(row["content"]),
                    score=self._rank_score(float(row["rank"])),
                    metadata=metadata,
                )
            )
        for row in faq_rows:
            hits.append(
                SearchHit(
                    id=str(row["id"]),
                    source_type="faq",
                    source_id=str(row["id"]),
                    content=f"Q: {row['question']}\nA: {row['answer']}",
                    score=self._rank_score(float(row["rank"])),
                    metadata=self._load_json(str(row["metadata_json"])),
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    def vector_search(self, query_embedding: list[float], limit: int) -> list[SearchHit]:
        hits: list[SearchHit] = []
        with self._connect() as connection:
            chunk_rows = connection.execute(
                """
                SELECT c.id, c.document_id AS source_id, c.content, c.metadata_json,
                       c.ordinal, c.embedding, c.embedding_dimensions, d.source_uri, d.title
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.active = 1 AND d.status = 'active'
                """
            ).fetchall()
            faq_rows = connection.execute(
                """
                SELECT id, question, answer, metadata_json, embedding, embedding_dimensions
                FROM faqs WHERE status = 'active'
                """
            ).fetchall()

        for row in chunk_rows:
            score = cosine_similarity(
                query_embedding,
                unpack_embedding(bytes(row["embedding"]), int(row["embedding_dimensions"])),
            )
            metadata = self._load_json(str(row["metadata_json"]))
            metadata.update(
                {
                    "source_uri": str(row["source_uri"]),
                    "title": str(row["title"]),
                    "ordinal": int(row["ordinal"]),
                }
            )
            hits.append(
                SearchHit(
                    id=str(row["id"]),
                    source_type="document",
                    source_id=str(row["source_id"]),
                    content=str(row["content"]),
                    score=score,
                    metadata=metadata,
                )
            )
        for row in faq_rows:
            score = cosine_similarity(
                query_embedding,
                unpack_embedding(bytes(row["embedding"]), int(row["embedding_dimensions"])),
            )
            hits.append(
                SearchHit(
                    id=str(row["id"]),
                    source_type="faq",
                    source_id=str(row["id"]),
                    content=f"Q: {row['question']}\nA: {row['answer']}",
                    score=score,
                    metadata=self._load_json(str(row["metadata_json"])),
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    def rebuild_fts_indexes(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks_fts")
            connection.execute("DELETE FROM faqs_fts")
            chunk_rows = connection.execute(
                "SELECT id, content FROM chunks WHERE active = 1"
            ).fetchall()
            faq_rows = connection.execute(
                "SELECT id, question, answer FROM faqs WHERE status = 'active'"
            ).fetchall()
            connection.executemany(
                "INSERT INTO chunks_fts (chunk_id, search_text) VALUES (?, ?)",
                [(str(row["id"]), fts_text(str(row["content"]))) for row in chunk_rows],
            )
            connection.executemany(
                "INSERT INTO faqs_fts (faq_id, search_text) VALUES (?, ?)",
                [
                    (
                        str(row["id"]),
                        fts_text(f"{row['question']} {row['answer']}"),
                    )
                    for row in faq_rows
                ],
            )

    def list_active_faq_questions(self) -> list[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, question FROM faqs WHERE status = 'active' ORDER BY id"
            ).fetchall()
        return [(str(row["id"]), str(row["question"])) for row in rows]

    def replace_faq_embeddings(
        self,
        embeddings: list[tuple[str, list[float]]],
    ) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                UPDATE faqs SET embedding = ?, embedding_dimensions = ? WHERE id = ?
                """,
                [
                    (pack_embedding(embedding), len(embedding), faq_id)
                    for faq_id, embedding in embeddings
                ],
            )

    def _insert_chunks(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        version_id: str,
        chunks: Iterable[ChunkCandidate],
        now: str,
    ) -> None:
        for chunk in chunks:
            chunk_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO chunks (
                    id, document_id, version_id, ordinal, content, content_hash,
                    token_count, metadata_json, embedding, embedding_dimensions, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    chunk_id,
                    document_id,
                    version_id,
                    chunk.ordinal,
                    chunk.content,
                    chunk.content_hash,
                    chunk.token_count,
                    self._json(chunk.metadata),
                    pack_embedding(chunk.embedding),
                    len(chunk.embedding),
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO chunks_fts (chunk_id, search_text) VALUES (?, ?)",
                (chunk_id, fts_text(chunk.content)),
            )

    def _document_select(self) -> str:
        return """
            SELECT d.*,
                   (SELECT COUNT(*) FROM chunks c
                    WHERE c.document_id = d.id AND c.active = 1) AS chunk_count
            FROM documents d
        """

    def _document_from_row(self, row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=str(row["id"]),
            source_uri=str(row["source_uri"]),
            title=str(row["title"]),
            mime_type=str(row["mime_type"]),
            content_hash=str(row["content_hash"]),
            current_version=int(row["current_version"]),
            status=str(row["status"]),
            chunk_count=int(row["chunk_count"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            metadata=self._load_json(str(row["metadata_json"])),
        )

    def _connect(self) -> sqlite3.Connection:
        return self.database.connect()

    def _json(self, value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _load_json(self, value: str) -> dict[str, Any]:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _rank_score(self, rank: float) -> float:
        return 1.0 / (1.0 + abs(rank))

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
