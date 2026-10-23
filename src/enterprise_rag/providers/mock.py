import json
import re
from typing import Any

from enterprise_rag.providers.base import GenerationRequest, GenerationResponse, ModelProvider


class MockModelProvider(ModelProvider):
    name = "mock"
    model = "deterministic-mock-v1"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        last_user_message = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            request.messages[-1].content,
        )
        structured = self._grounded_response(last_user_message)
        return GenerationResponse(
            text=structured if structured is not None else f"[mock] {last_user_message}",
            provider=self.name,
            model=self.model,
            finish_reason="stop",
        )

    def _grounded_response(self, message: str) -> str | None:
        try:
            payload: Any = json.loads(message)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or payload.get("operation") not in {
            "grounded_answer",
            "repair_grounded_answer",
        }:
            return None
        evidence = payload.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return json.dumps(
                {"answer": "证据不足。", "relevance_score": 0.1, "accuracy_score": 0.1},
                ensure_ascii=False,
            )
        query_terms = self._terms(str(payload.get("query", "")))
        query = str(payload.get("query", ""))
        candidates: list[tuple[str, int]] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            index = int(item.get("index", 1))
            parts = [
                part.strip(" #>*+-\t")
                for part in re.split(r"\n+|(?<=[。！？!?])", content)
                if len(part.strip(" #>*+-\t")) >= 4
            ]
            candidates.extend((part, index) for part in (parts or [content]) if part)
        if not candidates:
            return json.dumps(
                {"answer": "证据不足。", "relevance_score": 0.1, "accuracy_score": 0.1},
                ensure_ascii=False,
            )
        sentence, index = max(
            candidates,
            key=lambda item: self._candidate_score(item[0], query, query_terms),
        )
        sentence = sentence.rstrip("。！？!?；;")
        return json.dumps(
            {
                "answer": f"{sentence} [{index}]。",
                "relevance_score": 0.99,
                "accuracy_score": 0.99,
            },
            ensure_ascii=False,
        )

    def _terms(self, text: str) -> set[str]:
        lowered = text.casefold()
        terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", lowered))
        terms.update(
            lowered[index : index + 2]
            for index in range(len(lowered) - 1)
            if "\u4e00" <= lowered[index] <= "\u9fff" and "\u4e00" <= lowered[index + 1] <= "\u9fff"
        )
        return terms

    def _candidate_score(
        self,
        sentence: str,
        query: str,
        query_terms: set[str],
    ) -> tuple[int, int, int, int, int]:
        """Prefer declarative, policy-bearing evidence over headings and disclaimers."""
        normalized_sentence = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", sentence.casefold())
        normalized_query = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", query.casefold())
        answer_markers = ("可以", "应当", "应", "需要", "核验", "处理", "为", "是", "包括")
        boilerplate_markers = ("仅用于", "不构成", "演示数据", "回归问题")
        return (
            int(not normalized_query or normalized_sentence != normalized_query),
            -sum(marker in sentence for marker in boilerplate_markers),
            sum(marker in sentence for marker in answer_markers),
            len(query_terms & self._terms(sentence)),
            min(len(sentence), 160),
        )

