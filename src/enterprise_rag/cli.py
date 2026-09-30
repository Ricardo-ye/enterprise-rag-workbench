import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from enterprise_rag.acceptance.runner import AcceptanceRunner
from enterprise_rag.core.config import Settings
from enterprise_rag.generalization.models import GeneralizationDataset
from enterprise_rag.generalization.runner import GeneralizationRunner
from enterprise_rag.generation.models import AnswerEvaluationCase
from enterprise_rag.storage.sqlite import SQLiteDatabase


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="enterprise-rag")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate", help="Run an answer evaluation dataset")
    evaluate.add_argument("--dataset", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--base-url", default="http://127.0.0.1:8000")
    evaluate.add_argument("--api-key", default=os.getenv("RAG_API_KEY"))
    accept = subparsers.add_parser("accept", help="Run the final end-to-end suite")
    accept.add_argument("--output", type=Path, required=True)
    accept.add_argument("--base-url", default="http://127.0.0.1:8000")
    accept.add_argument("--api-key", default=os.getenv("RAG_API_KEY"))
    generalize = subparsers.add_parser(
        "generalize",
        help="Run the data-driven generalization and stability suite",
    )
    generalize.add_argument("--dataset", type=Path, required=True)
    generalize.add_argument("--output", type=Path, required=True)
    generalize.add_argument("--base-url", default="http://127.0.0.1:8000")
    generalize.add_argument("--api-key", default=os.getenv("RAG_API_KEY"))
    generalize.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit code when any expectation fails",
    )
    storage = subparsers.add_parser("storage", help="Inspect and back up persistent data")
    storage.add_argument("--database", type=Path)
    storage_commands = storage.add_subparsers(dest="storage_command", required=True)
    storage_commands.add_parser("verify", help="Run integrity and schema checks")
    backup = storage_commands.add_parser("backup", help="Create a verified online backup")
    backup.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.command == "evaluate":
        _run_evaluation(
            dataset=Path(args.dataset),
            output=Path(args.output),
            base_url=str(args.base_url),
            api_key=str(args.api_key) if args.api_key else None,
        )
    elif args.command == "accept":
        _run_acceptance(
            output=Path(args.output),
            base_url=str(args.base_url),
            api_key=str(args.api_key) if args.api_key else None,
        )
    elif args.command == "generalize":
        _run_generalization(
            dataset=Path(args.dataset),
            output=Path(args.output),
            base_url=str(args.base_url),
            api_key=str(args.api_key) if args.api_key else None,
            strict=bool(args.strict),
        )
    elif args.command == "storage":
        settings = Settings()
        database_path = Path(args.database) if args.database else settings.database_path
        database = SQLiteDatabase(
            database_path,
            busy_timeout_ms=settings.sqlite_busy_timeout_ms,
            synchronous=settings.sqlite_synchronous,
        )
        if args.storage_command == "verify":
            _run_storage_verify(database)
        elif args.storage_command == "backup":
            output = (
                Path(args.output)
                if args.output
                else settings.database_backup_directory
                / f"enterprise-rag-{database_timestamp()}.db"
            )
            _run_storage_backup(database, output)


def _run_evaluation(
    *,
    dataset: Path,
    output: Path,
    base_url: str,
    api_key: str | None,
) -> None:
    try:
        loaded: Any = json.loads(dataset.read_text(encoding="utf-8"))
        raw_cases = loaded.get("cases") if isinstance(loaded, dict) else loaded
        cases = TypeAdapter(list[AnswerEvaluationCase]).validate_python(raw_cases)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise SystemExit(f"Invalid evaluation dataset: {exc}") from exc
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/v1/rag/evaluate/answers",
            json={"cases": [case.model_dump(mode="json") for case in cases]},
            headers=headers,
            timeout=300,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SystemExit(f"Evaluation request failed: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(response.json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    body = response.json()
    print(
        f"cases={body['case_count']} "
        f"answer_success={body['answer_success_rate']:.3f} "
        f"refusal_accuracy={body['refusal_accuracy']:.3f} "
        f"p95_ms={body['p95_latency_ms']:.2f}"
    )


def _run_acceptance(*, output: Path, base_url: str, api_key: str | None) -> None:
    headers = {"X-API-Key": api_key} if api_key else {}
    with httpx.Client(base_url=base_url, headers=headers, timeout=300) as client:
        report = AcceptanceRunner(client, base_url=base_url).run()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"status={report.status} total={report.total} "
        f"passed={report.passed} failed={report.failed} "
        f"duration_ms={report.duration_ms:.2f}"
    )
    if report.status != "passed":
        raise SystemExit(1)


def _run_generalization(
    *,
    dataset: Path,
    output: Path,
    base_url: str,
    api_key: str | None,
    strict: bool,
) -> None:
    try:
        loaded: Any = json.loads(dataset.read_text(encoding="utf-8"))
        validation_dataset = GeneralizationDataset.model_validate(loaded)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise SystemExit(f"Invalid generalization dataset: {exc}") from exc
    headers = {"X-API-Key": api_key} if api_key else {}
    with httpx.Client(base_url=base_url, headers=headers, timeout=300) as client:
        report = GeneralizationRunner(client, base_url=base_url).run(validation_dataset)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"status={report.status} total={report.total} passed={report.passed} "
        f"failed={report.failed} pass_rate={report.pass_rate:.3f} "
        f"duration_ms={report.duration_ms:.2f}"
    )
    for group in report.groups:
        print(
            f"group={group.id} passed={group.passed}/{group.total} "
            f"pass_rate={group.pass_rate:.3f}"
        )
    if strict and report.failed:
        raise SystemExit(1)


def database_timestamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _run_storage_verify(database: SQLiteDatabase) -> None:
    check = database.verify()
    print(check.model_dump_json(indent=2))
    if not check.healthy:
        raise SystemExit(1)


def _run_storage_backup(database: SQLiteDatabase, output: Path) -> None:
    try:
        result = database.backup(output)
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Storage backup failed: {exc}") from exc
    print(result.model_dump_json(indent=2))
