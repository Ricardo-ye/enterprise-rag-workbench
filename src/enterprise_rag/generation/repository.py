import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from enterprise_rag.generation.models import AnswerQualitySummary, RagAnswerResult
from enterprise_rag.storage.sqlite import SQLiteDatabase, coerce_sqlite_database


class AnswerRecordRepository:
    def __init__(self, database_path: Path | SQLiteDatabase) -> None:
        self.database = coerce_sqlite_database(database_path)
        self.database_path = self.database.path

    def initialize(self) -> None:
        self.database.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS answer_quality_records (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL,
                    final_answer TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    repaired INTEGER NOT NULL,
                    used_citations_json TEXT NOT NULL,
                    attempts_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_answer_quality_records_created
                ON answer_quality_records(created_at)
                """
            )

    def save(self, result: RagAnswerResult) -> str:
        record_id = uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO answer_quality_records (
                    id, query, status, final_answer, confidence, repaired,
                    used_citations_json, attempts_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    result.query,
                    result.status,
                    result.answer,
                    result.confidence,
                    int(result.repaired),
                    json.dumps(result.used_citation_indices),
                    json.dumps(
                        [attempt.model_dump(mode="json") for attempt in result.attempts],
                        ensure_ascii=False,
                    ),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return record_id

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM answer_quality_records"
            ).fetchone()
        return int(row["count"]) if row else 0

    def summary(self) -> AnswerQualitySummary:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'answered' THEN 1 ELSE 0 END) AS answered,
                       SUM(CASE WHEN status = 'insufficient_evidence' THEN 1 ELSE 0 END)
                           AS insufficient_evidence,
                       SUM(CASE WHEN status = 'needs_human' THEN 1 ELSE 0 END)
                           AS needs_human,
                       SUM(CASE WHEN repaired = 1 THEN 1 ELSE 0 END) AS repaired
                FROM answer_quality_records
                """
            ).fetchone()
        return AnswerQualitySummary(
            total=int(row["total"] or 0),
            answered=int(row["answered"] or 0),
            insufficient_evidence=int(row["insufficient_evidence"] or 0),
            needs_human=int(row["needs_human"] or 0),
            repaired=int(row["repaired"] or 0),
        )

    def _connect(self) -> sqlite3.Connection:
        return self.database.connect()
