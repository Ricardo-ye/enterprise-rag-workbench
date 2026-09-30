from typing import Any

import httpx

from enterprise_rag.core.errors import ProviderError
from enterprise_rag.providers.base import GenerationRequest, GenerationResponse, ModelProvider


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self, *, base_url: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.model_dump() for message in request.messages],
            "stream": False,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
            return GenerationResponse(
                text=body["message"]["content"],
                provider=self.name,
                model=body.get("model", self.model),
                finish_reason=body.get("done_reason"),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError("Ollama request failed", provider=self.name) from exc

    async def close(self) -> None:
        await self._client.aclose()
