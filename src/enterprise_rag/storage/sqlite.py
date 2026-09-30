import hashlib
import json
import os
import sqlite3
from collections.abc import Collection
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

CURRENT_SCHEMA_VERSION = 1
CORE_TABLES = frozenset(
    {
        "documents",
        "chunks",
        "faqs",
        "task_sessions",
        "kg_triples",
        "answer_quality_records",
    }
)


class _ClosingSQLiteConnection(sqlite3.Connection):
    """Commit or roll back like sqlite3.Connection, then always release the file."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class StorageCheck(BaseModel):
    backend: Literal["sqlite"] = "sqlite"
    path: str
    healthy: bool
    integrity: str
    schema_version: int
    expected_schema_version: int = CURRENT_SCHEMA_VERSION
    journal_mode: str | None = None
    table_count: int = 0
    missing_tables: list[str] = Field(default_factory=list)
    size_bytes: int = 0
    checked_at: datetime


class BackupResult(BaseModel):
    backend: Literal["sqlite"] = "sqlite"
    source: str
    output: str
    manifest: str
    sha256: str
    size_bytes: int
    schema_version: int
    table_count: int
    created_at: datetime


class SQLiteDatabase:
    """Own SQLite connection policy, schema metadata, checks, and online backups."""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = 30_000,
        synchronous: Literal["OFF", "NORMAL", "FULL", "EXTRA"] = "NORMAL",
    ) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self.synchronous = synchronous

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            factory=_ClosingSQLiteConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute(f"PRAGMA synchronous={self.synchronous}")
        return connection

    def finalize_schema(self, version: int = CURRENT_SCHEMA_VERSION) -> None:
        with self.connect() as connection:
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            recorded_version = int(row[0] or 0)
            current_version = max(user_version, recorded_version)
            if current_version > version:
                raise RuntimeError(
                    f"Database schema {current_version} is newer than application schema {version}"
                )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
            connection.execute(f"PRAGMA user_version={version}")

    def verify(
        self,
        required_tables: Collection[str] | None = CORE_TABLES,
    ) -> StorageCheck:
        checked_at = datetime.now(UTC)
        resolved = self.path.resolve()
        if not self.path.is_file():
            integrity = "missing" if not self.path.exists() else "error:not_a_file"
            return StorageCheck(
                path=str(resolved),
                healthy=False,
                integrity=integrity,
                schema_version=0,
                missing_tables=sorted(required_tables or set()),
                checked_at=checked_at,
            )
        try:
            with self.connect() as connection:
                integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
                journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
                schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
        except sqlite3.Error as exc:
            return StorageCheck(
                path=str(resolved),
                healthy=False,
                integrity=f"error:{type(exc).__name__}",
                schema_version=0,
                missing_tables=sorted(required_tables or set()),
                size_bytes=self.path.stat().st_size if self.path.is_file() else 0,
                checked_at=checked_at,
            )
        missing = sorted(set(required_tables or ()) - tables)
        healthy = integrity == "ok" and not missing and schema_version == CURRENT_SCHEMA_VERSION
        return StorageCheck(
            path=str(resolved),
            healthy=healthy,
            integrity=integrity,
            schema_version=schema_version,
            journal_mode=journal_mode,
            table_count=len(tables),
            missing_tables=missing,
            size_bytes=self.path.stat().st_size,
            checked_at=checked_at,
        )

    def backup(self, output: Path) -> BackupResult:
        source = self.path.resolve()
        destination = output.resolve()
        check = self.verify()
        if not check.healthy:
            raise RuntimeError(
                "Source database failed integrity or schema checks: "
                f"integrity={check.integrity}, schema={check.schema_version}"
            )
        if source == destination:
            raise ValueError("Backup output must differ from the source database")
        if output.exists():
            raise FileExistsError(f"Backup output already exists: {destination}")

        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = output.with_suffix(f"{output.suffix}.manifest.json")
        if manifest.exists():
            raise FileExistsError(f"Backup manifest already exists: {manifest.resolve()}")
        temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
        try:
            with (
                self.connect() as source_connection,
                sqlite3.connect(temporary, factory=_ClosingSQLiteConnection) as target_connection,
            ):
                source_connection.backup(target_connection)
            with sqlite3.connect(temporary, factory=_ClosingSQLiteConnection) as target_connection:
                integrity = str(target_connection.execute("PRAGMA quick_check").fetchone()[0])
                if integrity != "ok":
                    raise RuntimeError(f"Backup integrity check failed: {integrity}")
                schema_version = int(target_connection.execute("PRAGMA user_version").fetchone()[0])
                table_count = int(
                    target_connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                    ).fetchone()[0]
                )
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)

        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        result = BackupResult(
            source=str(source),
            output=str(destination),
            manifest=str(manifest.resolve()),
            sha256=digest,
            size_bytes=output.stat().st_size,
            schema_version=schema_version,
            table_count=table_count,
            created_at=datetime.now(UTC),
        )
        manifest.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result


def coerce_sqlite_database(database: Path | SQLiteDatabase) -> SQLiteDatabase:
    return database if isinstance(database, SQLiteDatabase) else SQLiteDatabase(database)
