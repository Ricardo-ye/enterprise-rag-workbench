import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from enterprise_rag.storage.sqlite import SQLiteDatabase, coerce_sqlite_database
from enterprise_rag.taskflow.models import TaskSession, TaskStatus


class TaskRepository:
    def __init__(self, database_path: Path | SQLiteDatabase) -> None:
        self.database = coerce_sqlite_database(database_path)
        self.database_path = self.database.path

    def initialize(self) -> None:
        self.database.initialize()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_sessions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'cancelled')),
                    slots_json TEXT NOT NULL,
                    missing_slots_json TEXT NOT NULL,
                    action_result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_sessions_conversation
                    ON task_sessions(conversation_id, status, updated_at);

                CREATE TABLE IF NOT EXISTS task_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES task_sessions(id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_session
                    ON task_events(session_id, created_at);
                """
            )

    def create(
        self,
        *,
        conversation_id: str,
        intent: str,
        missing_slots: list[str],
    ) -> TaskSession:
        session_id = uuid4().hex
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_sessions (
                    id, conversation_id, intent, status, slots_json, missing_slots_json,
                    action_result_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', '{}', ?, NULL, ?, ?)
                """,
                (session_id, conversation_id, intent, self._json(missing_slots), now, now),
            )
            self._add_event(connection, session_id, "created", {"intent": intent})
        session = self.get(session_id)
        if session is None:
            raise RuntimeError("Task session disappeared after creation")
        return session

    def get(self, session_id: str) -> TaskSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def get_active(self, conversation_id: str) -> TaskSession | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM task_sessions
                WHERE conversation_id = ? AND status = 'active'
                ORDER BY updated_at DESC LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_latest(self, conversation_id: str) -> TaskSession | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM task_sessions
                WHERE conversation_id = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def update_slots(
        self,
        session_id: str,
        *,
        slots: dict[str, Any],
        missing_slots: list[str],
    ) -> TaskSession:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_sessions
                SET slots_json = ?, missing_slots_json = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (self._json(slots), self._json(missing_slots), now, session_id),
            )
            self._add_event(
                connection,
                session_id,
                "slots_updated",
                {"slots": slots, "missing_slots": missing_slots},
            )
        session = self.get(session_id)
        if session is None:
            raise RuntimeError("Task session not found after slot update")
        return session

    def complete(self, session_id: str, action_result: dict[str, Any]) -> TaskSession:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_sessions
                SET status = 'completed', missing_slots_json = '[]',
                    action_result_json = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (self._json(action_result), now, session_id),
            )
            self._add_event(connection, session_id, "completed", action_result)
        session = self.get(session_id)
        if session is None:
            raise RuntimeError("Task session not found after completion")
        return session

    def cancel(self, session_id: str, *, reason: str) -> TaskSession:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_sessions SET status = 'cancelled', updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now, session_id),
            )
            self._add_event(connection, session_id, "cancelled", {"reason": reason})
        session = self.get(session_id)
        if session is None:
            raise RuntimeError("Task session not found after cancellation")
        return session

    def _add_event(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO task_events (id, session_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uuid4().hex, session_id, event_type, self._json(payload), self._now()),
        )

    def _from_row(self, row: sqlite3.Row) -> TaskSession:
        action_result = (
            self._load_json(str(row["action_result_json"]))
            if row["action_result_json"] is not None
            else None
        )
        return TaskSession(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            intent=str(row["intent"]),
            status=TaskStatus(str(row["status"])),
            slots=self._load_json(str(row["slots_json"])),
            missing_slots=list(json.loads(str(row["missing_slots_json"]))),
            action_result=action_result,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _connect(self) -> sqlite3.Connection:
        return self.database.connect()

    def _json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _load_json(self, value: str) -> dict[str, Any]:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()
