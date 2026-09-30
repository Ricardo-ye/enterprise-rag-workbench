import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from enterprise_rag.kbqa.models import KgImportSummary, KgTripleInput, KnowledgeCandidate
from enterprise_rag.knowledge.embeddings import cosine_similarity, unpack_embedding
from enterprise_rag.knowledge.text import (
    fts_query,
    normalize_faq_question,
    normalized_tokens,
)
from enterprise_rag.storage.sqlite import SQLiteDatabase, coerce_sqlite_database


class KbqaRepository:
    def __init__(self, database_path: Path | SQLiteDatabase) -> None:
        self.database = coerce_sqlite_database(database_path)
        self.database_path = self.database.path

    def initialize(self) -> None:
        self.database.initialize()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS kg_triples (
                    id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    subject_normalized TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    predicate_normalized TEXT NOT NULL,
                    object TEXT NOT NULL,
                    subject_aliases_json TEXT NOT NULL,
                    predicate_aliases_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'deleted')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(subject_normalized, predicate_normalized)
                );
                CREATE INDEX IF NOT EXISTS idx_kg_triples_active
                    ON kg_triples(status, subject_normalized, predicate_normalized);
                """
            )

    def exact_faq(self, query: str) -> KnowledgeCandidate | None:
        normalized = normalize_faq_question(query)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, question, answer, metadata_json
                FROM faqs
                WHERE question_normalized = ? AND status = 'active' AND approved = 1
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return KnowledgeCandidate(
            source_type="faq",
            source_id=str(row["id"]),
            answer=str(row["answer"]),
            confidence=1.0,
            evidence={
                "question": str(row["question"]),
                "metadata": self._load_json(str(row["metadata_json"])),
                "approved": True,
            },
        )

    def faq_recall(
        self,
        query: str,
        query_embedding: list[float],
        *,
        limit: int,
    ) -> list[KnowledgeCandidate]:
        match_query = fts_query(query)
        if not match_query:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.id, f.question, f.answer, f.metadata_json,
                       f.embedding, f.embedding_dimensions
                FROM faqs_fts
                JOIN faqs f ON f.id = faqs_fts.faq_id
                WHERE faqs_fts MATCH ? AND f.status = 'active' AND f.approved = 1
                LIMIT ?
                """,
                (match_query, max(limit * 4, 20)),
            ).fetchall()
        query_tokens = set(normalized_tokens(query))
        canonical_query = normalize_faq_question(query)
        candidates: list[KnowledgeCandidate] = []
        for row in rows:
            question = str(row["question"])
            question_tokens = set(normalized_tokens(question))
            intersection = len(query_tokens & question_tokens)
            query_coverage = intersection / max(len(query_tokens), 1)
            question_coverage = intersection / max(len(question_tokens), 1)
            lexical_score = max(query_coverage, question_coverage)
            canonical_question = normalize_faq_question(question)
            if canonical_question in canonical_query or canonical_query in canonical_question:
                lexical_score = max(lexical_score, 0.98)
            embedding = unpack_embedding(bytes(row["embedding"]), int(row["embedding_dimensions"]))
            vector_score = max(cosine_similarity(query_embedding, embedding), 0.0)
            confidence = min(0.65 * lexical_score + 0.35 * vector_score, 0.99)
            candidates.append(
                KnowledgeCandidate(
                    source_type="faq",
                    source_id=str(row["id"]),
                    answer=str(row["answer"]),
                    confidence=confidence,
                    evidence={
                        "question": question,
                        "lexical_score": round(lexical_score, 6),
                        "vector_score": round(vector_score, 6),
                        "metadata": self._load_json(str(row["metadata_json"])),
                    },
                )
            )
        return sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)[:limit]

    def kg_query(self, query: str, *, limit: int) -> list[KnowledgeCandidate]:
        canonical_query = normalize_faq_question(query)
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM kg_triples WHERE status = 'active'").fetchall()
        candidates: list[KnowledgeCandidate] = []
        for row in rows:
            subject = str(row["subject"])
            predicate = str(row["predicate"])
            subject_aliases = self._load_list(str(row["subject_aliases_json"]))
            predicate_aliases = self._load_list(str(row["predicate_aliases_json"]))
            subject_score, matched_subject = self._entity_score(
                canonical_query, subject, subject_aliases
            )
            predicate_score, matched_predicate = self._entity_score(
                canonical_query, predicate, predicate_aliases
            )
            if not subject_score or not predicate_score:
                continue
            confidence = min((subject_score + predicate_score) / 2, 0.99)
            candidates.append(
                KnowledgeCandidate(
                    source_type="kg",
                    source_id=str(row["id"]),
                    answer=f"{subject}的{predicate}是{row['object']}。",
                    confidence=confidence,
                    evidence={
                        "subject": subject,
                        "predicate": predicate,
                        "object": str(row["object"]),
                        "matched_subject": matched_subject,
                        "matched_predicate": matched_predicate,
                        "metadata": self._load_json(str(row["metadata_json"])),
                    },
                )
            )
        return sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)[:limit]

    def import_triples(self, triples: list[KgTripleInput]) -> KgImportSummary:
        counts = {"created": 0, "updated": 0}
        now = self._now()
        with self._connect() as connection:
            for triple in triples:
                subject_normalized = normalize_faq_question(triple.subject)
                predicate_normalized = normalize_faq_question(triple.predicate)
                existing = connection.execute(
                    """
                    SELECT id FROM kg_triples
                    WHERE subject_normalized = ? AND predicate_normalized = ?
                    """,
                    (subject_normalized, predicate_normalized),
                ).fetchone()
                if existing:
                    connection.execute(
                        """
                        UPDATE kg_triples
                        SET subject = ?, predicate = ?, object = ?, subject_aliases_json = ?,
                            predicate_aliases_json = ?, metadata_json = ?, status = 'active',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            triple.subject,
                            triple.predicate,
                            triple.object,
                            self._json(triple.subject_aliases),
                            self._json(triple.predicate_aliases),
                            self._json(triple.metadata),
                            now,
                            str(existing["id"]),
                        ),
                    )
                    counts["updated"] += 1
                else:
                    connection.execute(
                        """
                        INSERT INTO kg_triples (
                            id, subject, subject_normalized, predicate, predicate_normalized,
                            object, subject_aliases_json, predicate_aliases_json, metadata_json,
                            status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                        """,
                        (
                            uuid4().hex,
                            triple.subject,
                            subject_normalized,
                            triple.predicate,
                            predicate_normalized,
                            triple.object,
                            self._json(triple.subject_aliases),
                            self._json(triple.predicate_aliases),
                            self._json(triple.metadata),
                            now,
                            now,
                        ),
                    )
                    counts["created"] += 1
        return KgImportSummary(**counts)

    def _entity_score(
        self,
        canonical_query: str,
        value: str,
        aliases: list[str],
    ) -> tuple[float, str | None]:
        if normalize_faq_question(value) in canonical_query:
            return 0.98, value
        for alias in aliases:
            if normalize_faq_question(alias) in canonical_query:
                return 0.93, alias
        return 0.0, None

    def _connect(self) -> sqlite3.Connection:
        return self.database.connect()

    def _json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _load_json(self, value: str) -> dict[str, Any]:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}

    def _load_list(self, value: str) -> list[str]:
        loaded = json.loads(value)
        return [str(item) for item in loaded] if isinstance(loaded, list) else []

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()
