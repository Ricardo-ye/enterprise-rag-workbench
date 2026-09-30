import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from enterprise_rag.cli import main
from enterprise_rag.storage.sqlite import CORE_TABLES, CURRENT_SCHEMA_VERSION, SQLiteDatabase


def _database(path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(path, busy_timeout_ms=2_000, synchronous="FULL")
    database.initialize()
    with database.connect() as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES ('persisted')")
        for table in CORE_TABLES:
            connection.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
    database.finalize_schema()
    return database


def _workspace() -> Path:
    path = Path("work/test-storage") / uuid4().hex
    path.mkdir(parents=True)
    return path


def test_storage_integrity_schema_and_online_backup() -> None:
    workspace = _workspace()
    database = _database(workspace / "source.db")

    check = database.verify({"sample"})
    assert check.healthy is True
    assert check.integrity == "ok"
    assert check.schema_version == CURRENT_SCHEMA_VERSION
    assert check.journal_mode == "wal"

    output = workspace / "backups" / "snapshot.db"
    result = database.backup(output)

    assert result.schema_version == CURRENT_SCHEMA_VERSION
    assert len(result.sha256) == 64
    assert output.is_file()
    manifest = json.loads(Path(result.manifest).read_text(encoding="utf-8"))
    assert manifest["sha256"] == result.sha256
    with sqlite3.connect(output) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "persisted"

    with pytest.raises(FileExistsError):
        database.backup(output)


def test_storage_cli_verify_and_backup(capsys: pytest.CaptureFixture[str]) -> None:
    workspace = _workspace()
    database = _database(workspace / "source.db")
    output = workspace / "cli-backup.db"

    main(["storage", "--database", str(database.path), "verify"])
    verify_output = json.loads(capsys.readouterr().out)
    assert verify_output["healthy"] is True

    main(
        [
            "storage",
            "--database",
            str(database.path),
            "backup",
            "--output",
            str(output),
        ]
    )
    backup_output = json.loads(capsys.readouterr().out)
    assert backup_output["output"] == str(output.resolve())
    assert output.is_file()


def test_storage_verify_fails_for_uninitialized_database() -> None:
    database = SQLiteDatabase(_workspace() / "missing.db")
    check = database.verify()
    assert check.healthy is False
    assert check.integrity == "missing"
    with pytest.raises(SystemExit) as exc_info:
        main(["storage", "--database", str(database.path), "verify"])
    assert exc_info.value.code == 1


def test_storage_refuses_schema_downgrade() -> None:
    database = SQLiteDatabase(_workspace() / "future.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(f"PRAGMA user_version={CURRENT_SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="newer than application schema"):
        database.finalize_schema()
