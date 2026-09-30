from enterprise_rag.core.config import Settings
from enterprise_rag.core.errors import ConfigurationError
from enterprise_rag.providers.base import ModelProvider
from enterprise_rag.providers.mock import MockModelProvider
from enterprise_rag.providers.ollama import OllamaProvider
from enterprise_rag.providers.openai_compatible import OpenAICompatibleProvider


def create_model_provider(settings: Settings) -> ModelProvider:
    if settings.model_provider == "mock":
        return MockModelProvider()

    if settings.model_provider == "openai":
        if settings.openai_api_key is None or not settings.openai_api_key.get_secret_value():
            raise ConfigurationError("RAG_OPENAI_API_KEY is required for the openai provider")
        return OpenAICompatibleProvider(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_model,
            timeout=settings.model_timeout_seconds,
        )

    if settings.model_provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.model_timeout_seconds,
        )

    raise ConfigurationError(f"Unsupported model provider: {settings.model_provider}")
