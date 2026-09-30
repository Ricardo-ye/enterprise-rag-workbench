import math

from enterprise_rag.rag.models import (
    EvaluationCase,
    EvaluationCaseResult,
    RetrievalEvaluationResult,
)
from enterprise_rag.rag.service import RagService


class RetrieverEvaluator:
    def __init__(self, service: RagService) -> None:
        self.service = service

    def evaluate(self, cases: list[EvaluationCase], *, k: int) -> RetrievalEvaluationResult:
        results: list[EvaluationCaseResult] = []
        for case in cases:
            retrieval = self.service.retrieve(case.query)
            retrieved = list(dict.fromkeys(hit.source_id for hit in retrieval.hits))[:k]
            relevant = set(case.relevant_source_ids)
            relevant_ranks = [
                rank for rank, source_id in enumerate(retrieved, start=1) if source_id in relevant
            ]
            recalled = len(relevant.intersection(retrieved)) / len(relevant)
            reciprocal_rank = 1.0 / min(relevant_ranks) if relevant_ranks else 0.0
            gains = [1.0 if source_id in relevant else 0.0 for source_id in retrieved]
            dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, 1))
            ideal_count = min(len(relevant), k)
            idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
            results.append(
                EvaluationCaseResult(
                    query=case.query,
                    retrieved_source_ids=retrieved,
                    recall_at_k=recalled,
                    reciprocal_rank=reciprocal_rank,
                    ndcg_at_k=dcg / idcg if idcg else 0.0,
                )
            )
        count = len(results)
        return RetrievalEvaluationResult(
            k=k,
            case_count=count,
            recall_at_k=sum(item.recall_at_k for item in results) / count,
            mrr=sum(item.reciprocal_rank for item in results) / count,
            ndcg_at_k=sum(item.ndcg_at_k for item in results) / count,
            cases=results,
        )
