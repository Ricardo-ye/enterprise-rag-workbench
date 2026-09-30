# Open Source Release Guide

This guide lists the remaining repository hygiene work before publishing Enterprise
RAG on GitHub.

## Ready

- `README.md` explains the workbench, quick start, API surface, evaluation commands,
  production notes, and quality checks.
- `docs/OPERATIONS.md` contains deployment, health, metrics, backup, and incident
  troubleshooting notes.
- `docs/DELIVERY.md` describes the delivered scope, extension points, and production
  gaps.
- `docs/KNOWLEDGE_BASE.md` provides a structured article that can be uploaded into
  the RAG knowledge base for self-description.
- `CONTRIBUTING.md` defines local setup, checks, and pull-request expectations.
- `SECURITY.md` defines the expected vulnerability-reporting shape.
- `.github/workflows/ci.yml` runs linting, typing, and tests on pull requests.
- `.gitignore` excludes local databases, generated outputs, caches, and build
  artifacts.

## Owner Decisions Before Public Release

- Choose and add a real `LICENSE` file. GitHub recommends including a license so
  contributors and users understand the project's reuse terms.
- Replace the placeholder vulnerability-reporting paragraph in `SECURITY.md` with a
  monitored contact or GitHub private vulnerability reporting instructions.
- Decide whether to add a `CODE_OF_CONDUCT.md`.
- Add screenshots or a short GIF of the workbench if the repository is meant to be
  discovered by external users.
- Review `.env.example` one more time to ensure no private endpoints, credentials, or
  organization-specific host names are present.

## Suggested GitHub Description

Production-oriented Enterprise RAG reference service with FastAPI, document/FAQ/KG
ingestion, layered routing, five-route retrieval, evidence-grounded answer quality
gates, observability, and an integrated web workbench.

## Suggested Topics

`rag`, `retrieval-augmented-generation`, `fastapi`, `llm`, `knowledge-base`,
`kbqa`, `evaluation`, `observability`, `python`, `ai-safety`

## First Release Checklist

1. Run local quality checks.
2. Start the workbench and run final acceptance.
3. Upload `docs/KNOWLEDGE_BASE.md` through the knowledge API and verify search.
4. Add the selected license.
5. Initialize Git, review ignored files, and ensure no `.env`, local databases, or
   generated reports are staged.
6. Push to GitHub and confirm the repository landing page renders `README.md`.
