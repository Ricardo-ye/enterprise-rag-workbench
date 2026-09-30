from typing import Any

import httpx

from enterprise_rag.core.errors import ProviderError
from enterprise_rag.providers.base import GenerationRequest, GenerationResponse, ModelProvider


class OpenAICompatibleProvider(ModelProvider):
    name = "openai"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            choice = body["choices"][0]
            return GenerationResponse(
                text=choice["message"]["content"],
                provider=self.name,
                model=body.get("model", self.model),
                finish_reason=choice.get("finish_reason"),
            )
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("OpenAI-compatible request failed", provider=self.name) from exc

    async def close(self) -> None:
        await self._client.aclose()
