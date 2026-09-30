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
        if not isinstance(evidence, list) or not evidence or not isinstance(evidence[0], dict):
            return json.dumps(
                {"answer": "证据不足。", "relevance_score": 0.1, "accuracy_score": 0.1},
                ensure_ascii=False,
            )
        first = evidence[0]
        content = str(first.get("content", "")).strip()
        query_terms = self._terms(str(payload.get("query", "")))
        candidates = [
            part.strip(" #>*+-\t")
            for part in re.split(r"\n+|(?<=[。！？!?])", content)
            if len(part.strip(" #>*+-\t")) >= 4
        ]
        sentence = max(
            candidates or [content],
            key=lambda value: (
                int(bool(re.search(r"[。！？!?]$", value))),
                len(query_terms & self._terms(value)),
                min(len(value), 120),
            ),
        )
        sentence = sentence.rstrip("。！？!?；;")
        index = int(first.get("index", 1))
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
