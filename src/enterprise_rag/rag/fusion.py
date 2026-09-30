from collections.abc import Mapping

from enterprise_rag.rag.models import FusedHit, RetrievalHit, RetrievalRoute


def reciprocal_rank_fusion(
    route_hits: Mapping[RetrievalRoute, list[RetrievalHit]],
    *,
    rrf_k: int,
) -> list[FusedHit]:
    """Fuse ranked route results while retaining provenance for every contribution."""
    fused: dict[str, FusedHit] = {}
    for route, hits in route_hits.items():
        for rank, hit in enumerate(hits, start=1):
            key = _deduplication_key(hit)
            contribution = 1.0 / (rrf_k + rank)
            existing = fused.get(key)
            if existing is None:
                fused[key] = FusedHit(
                    id=hit.id,
                    source_type=hit.source_type,
                    source_id=hit.source_id,
                    content=hit.content,
                    title=hit.title,
                    source_uri=hit.source_uri,
                    retrieval_routes=[route],
                    route_ranks={route.value: rank},
                    route_scores={route.value: hit.score},
                    rrf_score=contribution,
                    metadata=hit.metadata,
                )
                continue
            previous_best_score = max(existing.route_scores.values(), default=0.0)
            existing.retrieval_routes.append(route)
            existing.route_ranks[route.value] = rank
            existing.route_scores[route.value] = hit.score
            existing.rrf_score += contribution
            if hit.score > previous_best_score:
                existing.content = hit.content
                existing.title = hit.title
                existing.source_uri = hit.source_uri
                existing.metadata = hit.metadata

    return sorted(
        fused.values(),
        key=lambda hit: (-hit.rrf_score, hit.source_type, hit.id),
    )


def _deduplication_key(hit: RetrievalHit) -> str:
    # A document may have many independently useful chunks. Other sources are atomic.
    identity = hit.id if hit.source_type == "document" else hit.source_id
    return f"{hit.source_type}:{identity}"
