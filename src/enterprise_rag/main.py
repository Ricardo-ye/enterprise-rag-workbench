from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from enterprise_rag import __version__
from enterprise_rag.api.router import api_router
from enterprise_rag.assistant.service import AssistantService
from enterprise_rag.core.config import Settings, get_settings
from enterprise_rag.core.errors import install_exception_handlers
from enterprise_rag.core.logging import configure_logging
from enterprise_rag.core.middleware import install_request_middleware
from enterprise_rag.core.readiness import ReadinessService
from enterprise_rag.generation.audit import GroundedAnswerAuditor
from enterprise_rag.generation.evaluation import AnswerEvaluator
from enterprise_rag.generation.repository import AnswerRecordRepository
from enterprise_rag.generation.service import AnswerGenerationService
from enterprise_rag.kbqa.audit import AnswerAuditor
from enterprise_rag.kbqa.repository import KbqaRepository
from enterprise_rag.kbqa.service import KbqaService
from enterprise_rag.knowledge.chunking import StructureAwareChunker
from enterprise_rag.knowledge.embeddings import HashingEmbeddingProvider
from enterprise_rag.knowledge.parsers import DocumentParser
from enterprise_rag.knowledge.repository import KnowledgeRepository
from enterprise_rag.knowledge.service import KnowledgeService
from enterprise_rag.observability.metrics import MetricsRegistry
from enterprise_rag.providers.factory import create_model_provider
from enterprise_rag.quality.repository import QualityRepository
from enterprise_rag.rag.evaluation import RetrieverEvaluator
from enterprise_rag.rag.rerankers import CrossEncoderReranker, HeuristicReranker
from enterprise_rag.rag.retrievers import (
    DisabledWebRetriever,
    FaqRetriever,
    KgRetriever,
    LexicalRetriever,
    SearxngWebRetriever,
    SemanticRetriever,
)
from enterprise_rag.rag.service import RagService
from enterprise_rag.routing.config import load_routing_config
from enterprise_rag.routing.service import RoutingService
from enterprise_rag.storage.sqlite import SQLiteDatabase
from enterprise_rag.taskflow.actions import ActionRegistry, MockBusinessActionAdapter
from enterprise_rag.taskflow.nlu import SlotExtractor
from enterprise_rag.taskflow.repository import TaskRepository
from enterprise_rag.taskflow.service import TaskFlowService

_UI_DIRECTORY = Path(__file__).parent / "ui"


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    configure_logging(runtime_settings.log_level)
    metrics_registry = MetricsRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = SQLiteDatabase(
            runtime_settings.database_path,
            busy_timeout_ms=runtime_settings.sqlite_busy_timeout_ms,
            synchronous=runtime_settings.sqlite_synchronous,
        )
        database.initialize()
        repository = KnowledgeRepository(database)
        repository.initialize()
        task_repository = TaskRepository(database)
        task_repository.initialize()
        kbqa_repository = KbqaRepository(database)
        kbqa_repository.initialize()
        answer_record_repository = AnswerRecordRepository(database)
        answer_record_repository.initialize()
        quality_repository = QualityRepository(database)
        quality_repository.initialize()
        database.finalize_schema()
        routing_config = load_routing_config(runtime_settings.routing_config_path)
        embedding_provider = HashingEmbeddingProvider(runtime_settings.embedding_dimensions)
        app.state.settings = runtime_settings
        app.state.database = database
        model_provider = create_model_provider(runtime_settings)
        app.state.model_provider = model_provider
        app.state.knowledge_service = KnowledgeService(
            repository=repository,
            parser=DocumentParser(),
            chunker=StructureAwareChunker(
                max_chars=runtime_settings.chunk_max_chars,
                overlap_chars=runtime_settings.chunk_overlap_chars,
            ),
            embedding_provider=embedding_provider,
            max_upload_bytes=runtime_settings.max_upload_bytes,
        )
        routing_service = RoutingService(
            config=routing_config,
            min_intent_confidence=runtime_settings.routing_min_intent_confidence,
            min_domain_confidence=runtime_settings.routing_min_domain_confidence,
            embedding_provider=embedding_provider,
            fallback_similarity_threshold=runtime_settings.routing_fallback_similarity,
        )
        action_registry = ActionRegistry(MockBusinessActionAdapter())
        taskflow_service = TaskFlowService(
            repository=task_repository,
            extractor=SlotExtractor(),
            actions=action_registry,
            intents=routing_config.intents,
        )
        kbqa_service = KbqaService(
            repository=kbqa_repository,
            embedding_provider=embedding_provider,
            auditor=AnswerAuditor(),
            first_gate_threshold=runtime_settings.kbqa_first_gate_threshold,
            second_gate_threshold=runtime_settings.kbqa_second_gate_threshold,
        )
        web_retriever = (
            SearxngWebRetriever(
                runtime_settings.searxng_base_url,
                runtime_settings.retrieval_timeout_ms / 1000,
            )
            if runtime_settings.web_search_provider == "searxng"
            else DisabledWebRetriever()
        )
        reranker = (
            CrossEncoderReranker(runtime_settings.cross_encoder_model)
            if runtime_settings.reranker_provider == "cross_encoder"
            else HeuristicReranker()
        )
        rag_service = RagService(
            retrievers=[
                SemanticRetriever(repository, embedding_provider),
                LexicalRetriever(repository),
                web_retriever,
                KgRetriever(kbqa_repository),
                FaqRetriever(kbqa_repository, embedding_provider),
            ],
            reranker=reranker,
            timeout_ms=runtime_settings.retrieval_timeout_ms,
            top_k_per_route=runtime_settings.retrieval_top_k_per_route,
            fused_top_k=runtime_settings.retrieval_fused_top_k,
            context_top_k=runtime_settings.retrieval_context_top_k,
            rrf_k=runtime_settings.rrf_k,
            circuit_failure_threshold=runtime_settings.circuit_failure_threshold,
            circuit_reset_seconds=runtime_settings.circuit_reset_seconds,
            metrics=metrics_registry,
        )
        generation_service = AnswerGenerationService(
            rag=rag_service,
            provider=model_provider,
            auditor=GroundedAnswerAuditor(
                min_grounding_coverage=runtime_settings.generation_min_grounding_coverage
            ),
            repository=answer_record_repository,
            self_score_threshold=runtime_settings.generation_self_score_threshold,
            post_audit_threshold=runtime_settings.generation_post_audit_threshold,
            min_evidence_score=runtime_settings.generation_min_evidence_score,
            min_query_coverage=runtime_settings.generation_min_query_coverage,
            max_tokens=runtime_settings.generation_max_tokens,
            store_records=runtime_settings.generation_store_records,
            metrics=metrics_registry,
        )
        app.state.routing_service = routing_service
        app.state.taskflow_service = taskflow_service
        app.state.kbqa_repository = kbqa_repository
        app.state.kbqa_service = kbqa_service
        app.state.rag_service = rag_service
        app.state.retriever_evaluator = RetrieverEvaluator(rag_service)
        app.state.answer_record_repository = answer_record_repository
        app.state.quality_repository = quality_repository
        app.state.generation_service = generation_service
        app.state.answer_evaluator = AnswerEvaluator(generation_service)
        app.state.readiness_service = ReadinessService(
            database,
            model_provider.name,
        )
        app.state.assistant_service = AssistantService(
            routing=routing_service,
            taskflow=taskflow_service,
            kbqa=kbqa_service,
            rag=rag_service,
            generation=generation_service,
        )
        yield
        await app.state.model_provider.close()

    app = FastAPI(
        title="Enterprise RAG API",
        description="Layered enterprise RAG service",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if runtime_settings.environment == "production" else "/docs",
        redoc_url=None if runtime_settings.environment == "production" else "/redoc",
    )
    app.state.metrics_registry = metrics_registry
    allowed_hosts = [
        host.strip() for host in runtime_settings.trusted_hosts.split(",") if host.strip()
    ]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    install_request_middleware(app, runtime_settings, metrics_registry)
    install_exception_handlers(app)
    app.include_router(api_router)
    app.mount("/assets", StaticFiles(directory=_UI_DIRECTORY), name="ui-assets")

    @app.get("/", include_in_schema=False, response_class=FileResponse)
    @app.get("/ui", include_in_schema=False, response_class=FileResponse)
    async def workspace() -> FileResponse:
        return FileResponse(_UI_DIRECTORY / "index.html", media_type="text/html")

    return app


app = create_app()

