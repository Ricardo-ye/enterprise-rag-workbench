# Enterprise RAG Knowledge Base

## Purpose

This document is the project-facing knowledge base article for the Enterprise RAG
system. It is designed to be uploaded into the service itself, so that the workbench
can answer questions about the architecture, operating model, safety controls, and
release readiness of this repository.

## System Scope

Enterprise RAG is a FastAPI-based retrieval-augmented generation service with a
single-page workbench. It supports document, FAQ, and knowledge-graph ingestion;
layered routing; task-flow handling; five-route retrieval; answer generation with
quality gates; metrics; and local/offline regression tests.

The current implementation is suitable for local demonstrations, deterministic
acceptance testing, and architectural review. Production use still requires real
embedding and generation providers, identity integration, tenant isolation, durable
multi-instance storage, and organization-specific security review.

## Architecture Overview

The service follows a layered RAG flow:

1. A user submits a query through the workbench or API.
2. Middleware applies request IDs, timing, API key checks, trusted-host checks, and
   rate limiting.
3. The routing layer performs safety screening, actor classification, domain
   detection, sub-intent classification, and task-vs-question dispatch.
4. Task-oriented requests enter Task Flow, where required slots are collected and a
   local action adapter produces a simulated business result.
5. Knowledge questions first try KBQA, including exact approved FAQ matches,
   FAQ recall, and knowledge-graph triples with confidence gates.
6. RAG fallback runs semantic, lexical, web, knowledge-graph, and FAQ routes. Results
   are fused with reciprocal rank fusion, deduplicated, and reranked.
7. The generation layer builds evidence-grounded prompts and requires structured JSON
   output with answer text and self-scores.
8. Quality gates validate relevance, accuracy, citations, evidence support, risky
   commitments, prompt-injection wording, and completeness.
9. Failed first attempts get one repair pass. Continued failure returns
   `needs_human`; weak evidence returns `insufficient_evidence`.
10. Metrics, SLO snapshots, answer-quality records, and route traces make the result
    auditable.

## Core Modules

| Area | Main path | Responsibility |
| --- | --- | --- |
| API composition | `src/enterprise_rag/main.py` | Builds the FastAPI app, dependencies, middleware, static UI, and lifecycle hooks. |
| Knowledge lifecycle | `src/enterprise_rag/knowledge/` | Parses Markdown, TXT, and PDF files; chunks content; manages documents, FAQ, indexes, and embeddings. |
| Routing | `src/enterprise_rag/routing/` | Classifies safety, audience, domain, intent, and target module. |
| Task Flow | `src/enterprise_rag/taskflow/` | Maintains multi-turn task state, slot filling, and simulated actions. |
| KBQA | `src/enterprise_rag/kbqa/` | Handles approved FAQ fast paths, FAQ/KG candidates, and KBQA quality gates. |
| RAG retrieval | `src/enterprise_rag/rag/` | Runs multi-route retrieval, fusion, reranking, context packaging, and retrieval evaluation. |
| Generation | `src/enterprise_rag/generation/` | Performs evidence-grounded generation, parsing, auditing, repair, and answer-quality persistence. |
| Observability | `src/enterprise_rag/observability/` | Exposes Prometheus-style metrics and process-level SLO snapshots. |
| UI | `src/enterprise_rag/ui/` | Provides the interactive workbench without a separate frontend build step. |
| Evaluation | `evals/`, `src/enterprise_rag/acceptance/`, `src/enterprise_rag/generalization/` | Defines acceptance, answer-quality, generalization, abnormal-input, and stability checks. |

## Knowledge Ingestion Model

Documents can be uploaded through `POST /api/v1/knowledge/documents/ingest`.
Supported formats are Markdown, UTF-8 text, and extractable-text PDF. The service
stores a source URI, SHA-256 content hash, metadata, current version, and chunk
records. Re-uploading identical content is idempotent.

FAQ entries use `POST /api/v1/knowledge/faqs/import`. Only records with
`approved: true` can participate in exact answers and KBQA fast paths. This keeps
curated answers separate from raw documents.

Knowledge-graph triples are imported through `POST /api/v1/kbqa/kg/triples/import`.
They support structured answers for facts that are better represented as entities and
relations than long-form text.

## Retrieval and Generation Policy

The default local embedding provider is `hashing-v1`. It is deterministic and useful
for tests, but it is not a production semantic model. Before a public production
deployment, replace it with the organization's selected multilingual embedding model
and recalibrate thresholds with a representative evaluation set.

The service deliberately favors grounded refusal over unsupported answers:

- If retrieval evidence is weak, return `insufficient_evidence`.
- If generation cannot pass quality gates after one repair, return `needs_human`.
- If a request contains prompt injection or unsafe intent, route it to rejection or
  manual review instead of tool execution.
- If citations are missing, invalid, or unsupported by evidence, do not expose the
  answer as successful.

## Security Notes

The current code includes API key authentication, trusted-host enforcement, basic
rate limiting, upload-size limits, unsupported-file rejection, safe DOM rendering in
the workbench, and prompt-injection checks. These controls map to common LLM
application risks such as prompt injection, sensitive-information disclosure,
improper output handling, and excessive agency.

Before open production use, add organization-level controls:

- OIDC or mTLS at the gateway.
- User and tenant identity propagated to documents, FAQ, KG triples, task sessions,
  and answer-quality records.
- Role-based access control for ingestion, deletion, metrics, and backup operations.
- Secret management for provider keys.
- Log redaction and data-retention policy.
- Human review for high-impact business actions.
- Dependency, container, and prompt-injection security testing in CI.

## Evaluation Checklist

A release candidate should pass these local checks:

```powershell
uv run ruff check .
uv run mypy
uv run pytest --cov=enterprise_rag --cov-report=term-missing
uv run enterprise-rag accept --base-url http://127.0.0.1:8000 --output outputs/final-acceptance.json
uv run enterprise-rag generalize --dataset evals/generalization-stability.json --output outputs/generalization-stability-report.json --base-url http://127.0.0.1:8000
```

Known local limitation: the deterministic hashing embedder is weak on semantic
paraphrase, typo noise, cross-language queries, and conversation-history query
rewriting. Those gaps are documented in the generalization report and should be
treated as product improvement work, not merely test noise.

## Open Source Release Checklist

For GitHub publication, keep the root README concise and put deeper material under
`docs/`. The repository should include:

- `README.md` with purpose, screenshots or UI entry point, quick start, API summary,
  test commands, and documentation map.
- `CONTRIBUTING.md` with setup, coding style, tests, and pull-request expectations.
- `SECURITY.md` with vulnerability reporting guidance.
- `.env.example` without secrets.
- `.gitignore` that excludes local databases, generated outputs, virtual
  environments, coverage files, and caches.
- `.github/workflows/ci.yml` so every pull request runs linting, type checks, and
  tests.
- A project license chosen by the owner before public release.

## External References

- Microsoft Azure Architecture Center, "Design and develop a RAG solution":
  https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-solution-design-and-evaluation-guide
- Microsoft Azure Architecture Center, "RAG preparation phase":
  https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-preparation-phase
- Microsoft Azure Architecture Center, "RAG information-retrieval phase":
  https://learn.microsoft.com/azure/architecture/ai-ml/guide/rag/rag-information-retrieval
- Microsoft Azure AI Search, "Retrieval-augmented generation in Azure AI Search":
  https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview
- OWASP GenAI Security Project, "OWASP Top 10 for LLM Applications":
  https://genai.owasp.org/llm-top-10/
- GitHub Docs, "About README files":
  https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes
- GitHub Docs, "Best practices for repositories":
  https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories
