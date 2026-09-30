from concurrent.futures import Future, ThreadPoolExecutor, wait
from time import perf_counter

from enterprise_rag.observability.metrics import MetricsRegistry
from enterprise_rag.rag.circuit import CircuitBreaker, CircuitOpenError
from enterprise_rag.rag.fusion import reciprocal_rank_fusion
from enterprise_rag.rag.models import (
    Citation,
    RagRetrievalResult,
    RetrievalHit,
    RetrievalRoute,
    RouteExecution,
)
from enterprise_rag.rag.rerankers import Reranker
from enterprise_rag.rag.retrievers import Retriever


class RagService:
    def __init__(
        self,
        *,
        retrievers: list[Retriever],
        reranker: Reranker,
        timeout_ms: int,
        top_k_per_route: int,
        fused_top_k: int,
        context_top_k: int,
        rrf_k: int,
        circuit_failure_threshold: int,
        circuit_reset_seconds: float,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.retrievers = {retriever.route: retriever for retriever in retrievers}
        self.reranker = reranker
        self.timeout_seconds = timeout_ms / 1000.0
        self.top_k_per_route = top_k_per_route
        self.fused_top_k = fused_top_k
        self.context_top_k = context_top_k
        self.rrf_k = rrf_k
        self.metrics = metrics
        self.circuits = {
            route: CircuitBreaker(
                failure_threshold=circuit_failure_threshold,
                reset_seconds=circuit_reset_seconds,
            )
            for route in RetrievalRoute
        }

    def retrieve(self, query: str) -> RagRetrievalResult:
        normalized_query = query.strip()
        started = perf_counter()
        route_hits, executions = self._parallel_retrieve(normalized_query)
        if self.metrics:
            for execution in executions:
                self.metrics.record_retrieval(
                    execution.route.value,
                    execution.status,
                    execution.duration_ms / 1000,
                )
        fused = reciprocal_rank_fusion(route_hits, rrf_k=self.rrf_k)[: self.fused_top_k]
        ranked = self.reranker.rerank(normalized_query, fused)
        context_hits = ranked[: self.context_top_k]
        citations = [
            Citation(
                index=index,
                source_type=hit.source_type,
                source_id=hit.source_id,
                title=hit.title,
                source_uri=hit.source_uri,
                snippet=hit.content[:500],
                score=hit.rerank_score,
                retrieval_routes=hit.retrieval_routes,
                metadata=hit.metadata,
            )
            for index, hit in enumerate(context_hits, start=1)
        ]
        context = "\n\n".join(
            f"[{citation.index}] {citation.title}\n"
            f"{citation.snippet}\n"
            f"Source: {citation.source_uri}"
            for citation in citations
        )
        return RagRetrievalResult(
            query=normalized_query,
            hits=ranked,
            citations=citations,
            context=context,
            routes=executions,
            duration_ms=(perf_counter() - started) * 1000,
        )

    def _parallel_retrieve(
        self, query: str
    ) -> tuple[dict[RetrievalRoute, list[RetrievalHit]], list[RouteExecution]]:
        route_hits: dict[RetrievalRoute, list[RetrievalHit]] = {}
        executions: dict[RetrievalRoute, RouteExecution] = {}
        executor = ThreadPoolExecutor(max_workers=max(len(self.retrievers), 1))
        futures: dict[Future[list[RetrievalHit]], tuple[RetrievalRoute, float]] = {}
        try:
            for route in RetrievalRoute:
                retriever = self.retrievers.get(route)
                if retriever is None or not retriever.enabled:
                    executions[route] = RouteExecution(
                        route=route,
                        status="skipped",
                        duration_ms=0,
                        hit_count=0,
                    )
                    continue
                future = executor.submit(self._retrieve_one, retriever, query)
                futures[future] = (route, perf_counter())

            completed, pending = wait(futures, timeout=self.timeout_seconds)
            for future in completed:
                route, route_started = futures[future]
                duration_ms = (perf_counter() - route_started) * 1000
                try:
                    hits = future.result()
                except CircuitOpenError as exc:
                    executions[route] = RouteExecution(
                        route=route,
                        status="circuit_open",
                        duration_ms=duration_ms,
                        hit_count=0,
                        error=str(exc),
                    )
                except Exception as exc:
                    self.circuits[route].record_failure()
                    executions[route] = RouteExecution(
                        route=route,
                        status="error",
                        duration_ms=duration_ms,
                        hit_count=0,
                        error=str(exc)[:300],
                    )
                else:
                    self.circuits[route].record_success()
                    route_hits[route] = hits
                    executions[route] = RouteExecution(
                        route=route,
                        status="ok" if hits else "empty",
                        duration_ms=duration_ms,
                        hit_count=len(hits),
                    )

            for future in pending:
                route, route_started = futures[future]
                future.cancel()
                self.circuits[route].record_failure()
                executions[route] = RouteExecution(
                    route=route,
                    status="timeout",
                    duration_ms=(perf_counter() - route_started) * 1000,
                    hit_count=0,
                    error=f"route exceeded {self.timeout_seconds:.3f}s timeout",
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return route_hits, [executions[route] for route in RetrievalRoute]

    def _retrieve_one(self, retriever: Retriever, query: str) -> list[RetrievalHit]:
        self.circuits[retriever.route].before_call()
        return retriever.retrieve(query, self.top_k_per_route)
