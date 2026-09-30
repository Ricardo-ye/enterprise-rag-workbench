# Contributing

Thanks for improving Enterprise RAG. This project is intentionally small enough to
run locally, but it exercises a full RAG lifecycle, so contributions should preserve
determinism, testability, and evidence-grounded behavior.

## Local Setup

```powershell
uv sync
Copy-Item .env.example .env
uv run uvicorn enterprise_rag.main:app --host 127.0.0.1 --port 8000
```

Open the workbench at `http://127.0.0.1:8000/`.

## Quality Checks

Run these before opening a pull request:

```powershell
uv run ruff check .
uv run mypy
uv run pytest --cov=enterprise_rag --cov-report=term-missing
```

For changes that affect retrieval, routing, generation, safety, storage, or the UI,
also run the relevant acceptance command:

```powershell
uv run enterprise-rag accept --base-url http://127.0.0.1:8000 --output outputs/final-acceptance.json
uv run enterprise-rag generalize --dataset evals/generalization-stability.json --output outputs/generalization-stability-report.json --base-url http://127.0.0.1:8000
```

Generated files under `outputs/`, `work/`, and `data/` are local artifacts and should
not be committed.

## Pull Request Guidelines

- Keep changes scoped to one behavior or documentation topic.
- Add or update tests for user-visible behavior and shared service contracts.
- Do not weaken quality gates, safety checks, or refusal behavior without a clear
  evaluation update.
- Keep default tests offline and deterministic. Optional external providers should be
  configured through environment variables.
- Never commit secrets, API keys, private documents, local databases, or generated
  acceptance reports.
- Document production-impacting changes in `README.md`, `docs/OPERATIONS.md`, or
  `docs/KNOWLEDGE_BASE.md`.

## Documentation Style

Use `README.md` for quick-start and project orientation. Put operational runbooks,
release notes, and architectural detail in `docs/`. Knowledge that should be ingested
into the RAG service should be written as standalone Markdown with clear headings,
short paragraphs, and explicit source links.
