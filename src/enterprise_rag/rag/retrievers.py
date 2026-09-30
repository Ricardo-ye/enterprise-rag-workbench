from abc import ABC, abstractmethod
from typing import Any

import httpx

from enterprise_rag.kbqa.repository import KbqaRepository
from enterprise_rag.knowledge.embeddings import EmbeddingProvider
from enterprise_rag.knowledge.repository import KnowledgeRepository
from enterprise_rag.rag.models import RetrievalHit, RetrievalRoute


class Retriever(ABC):
    route: RetrievalRoute
    enabled: bool = True

    @abstractmethod
    def retrieve(self, query: str, limit: int) -> list[RetrievalHit]:
        """Retrieve evidence for one route."""


class SemanticRetriever(Retriever):
    route = RetrievalRoute.SEMANTIC

    def __init__(
        self,
        repository: KnowledgeRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def retrieve(self, query: str, limit: int) -> list[RetrievalHit]:
        embedding = self.embedding_provider.embed([query])[0]
        hits = self.repository.vector_search(embedding, limit * 3)
        return [
            RetrievalHit(
                id=hit.id,
                route=self.route,
                source_type="document",
                source_id=hit.source_id,
                content=hit.content,
                score=max(min(hit.score, 1.0), 0.0),
                title=str(hit.metadata.get("title", "Knowledge document")),
                source_uri=str(hit.metadata.get("source_uri", f"document://{hit.source_id}")),
                metadata=hit.metadata,
            )
            for hit in hits
            if hit.source_type == "document"
        ][:limit]


class LexicalRetriever(Retriever):
    route = RetrievalRoute.LEXICAL

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def retrieve(self, query: str, limit: int) -> list[RetrievalHit]:
        hits = self.repository.lexical_search(query, limit * 3)
        return [
            RetrievalHit(
                id=hit.id,
                route=self.route,
                source_type="document",
                source_id=hit.source_id,
                content=hit.content,
                score=max(min(hit.score, 1.0), 0.0),
                title=str(hit.metadata.get("title", "Knowledge document")),
                source_uri=str(hit.metadata.get("source_uri", f"document://{hit.source_id}")),
                metadata=hit.metadata,
            )
            for hit in hits
            if hit.source_type == "document"
        ][:limit]


class FaqRetriever(Retriever):
    route = RetrievalRoute.FAQ

    def __init__(
        self,
        repository: KbqaRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def retrieve(self, query: str, limit: int) -> list[RetrievalHit]:
        exact = self.repository.exact_faq(query)
        candidates = []
        if exact is not None:
            candidates.append(exact)
        embedding = self.embedding_provider.embed([query])[0]
        candidates.extend(self.repository.faq_recall(query, embedding, limit=limit))
        seen: set[str] = set()
        hits: list[RetrievalHit] = []
        for candidate in candidates:
            if candidate.source_id in seen:
                continue
            seen.add(candidate.source_id)
            question = str(candidate.evidence.get("question", "FAQ"))
            hits.append(
                RetrievalHit(
                    id=f"faq:{candidate.source_id}",
                    route=self.route,
                    source_type="faq",
                    source_id=candidate.source_id,
                    content=candidate.answer,
                    score=candidate.confidence,
                    title=question,
                    source_uri=f"faq://{candidate.source_id}",
                    metadata=candidate.evidence,
                )
            )
        return hits[:limit]


class KgRetriever(Retriever):
    route = RetrievalRoute.KG

    def __init__(self, repository: KbqaRepository) -> None:
        self.repository = repository

    def retrieve(self, query: str, limit: int) -> list[RetrievalHit]:
        return [
            RetrievalHit(
                id=f"kg:{candidate.source_id}",
                route=self.route,
                source_type="kg",
                source_id=candidate.source_id,
                content=candidate.answer,
                score=candidate.confidence,
                title=f"{candidate.evidence.get('subject', 'Entity')} · "
                f"{candidate.evidence.get('predicate', 'Fact')}",
                source_uri=f"kg://{candidate.source_id}",
                metadata=candidate.evidence,
            )
            for candidate in self.repository.kg_query(query, limit=limit)
        ]


class DisabledWebRetriever(Retriever):
    route = RetrievalRoute.WEB
    enabled = False

    def retrieve(self, query: str, limit: int) -> list[RetrievalHit]:
        return []


class SearxngWebRetriever(Retriever):
    route = RetrievalRoute.WEB

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def retrieve(self, query: str, limit: int) -> list[RetrievalHit]:
        response = httpx.get(
            f"{self.base_url}/search",
            params={"q": query, "format": "json"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body: Any = response.json()
        raw_results = body.get("results", []) if isinstance(body, dict) else []
        hits: list[RetrievalHit] = []
        for index, item in enumerate(raw_results[:limit]):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", ""))
            content = str(item.get("content") or item.get("title") or "").strip()
            if not url or not content:
                continue
            hits.append(
                RetrievalHit(
                    id=f"web:{url}",
                    route=self.route,
                    source_type="web",
                    source_id=url,
                    content=content,
                    score=max(0.0, 1.0 - index * 0.05),
                    title=str(item.get("title") or url),
                    source_uri=url,
                    metadata={"engine": item.get("engine")},
                )
            )
        return hits
