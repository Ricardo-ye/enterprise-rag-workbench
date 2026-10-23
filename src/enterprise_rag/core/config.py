from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_prefix="RAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "enterprise-rag"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_key: SecretStr | None = None
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    rate_limit_requests_per_minute: int = Field(default=120, ge=0, le=100000)

    model_provider: Literal["mock", "openai", "ollama"] = "mock"
    model_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    database_path: Path = Path("data/enterprise_rag.db")
    database_backup_directory: Path = Path("backups")
    sqlite_busy_timeout_ms: int = Field(default=30_000, ge=100, le=300_000)
    sqlite_synchronous: Literal["OFF", "NORMAL", "FULL", "EXTRA"] = "NORMAL"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024)
    chunk_max_chars: int = Field(default=1200, ge=200, le=10000)
    chunk_overlap_chars: int = Field(default=200, ge=0, le=2000)
    embedding_dimensions: int = Field(default=384, ge=64, le=4096)

    routing_config_path: Path = Path("config/routing.json")
    routing_min_intent_confidence: float = Field(default=0.65, ge=0, le=1)
    routing_min_domain_confidence: float = Field(default=0.55, ge=0, le=1)
    routing_fallback_similarity: float = Field(default=0.42, ge=0, le=1)

    kbqa_first_gate_threshold: float = Field(default=0.90, ge=0, le=1)
    kbqa_second_gate_threshold: float = Field(default=0.90, ge=0, le=1)

    retrieval_timeout_ms: int = Field(default=1500, ge=50, le=30000)
    retrieval_top_k_per_route: int = Field(default=10, ge=1, le=100)
    retrieval_fused_top_k: int = Field(default=20, ge=1, le=200)
    retrieval_context_top_k: int = Field(default=5, ge=1, le=50)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    circuit_failure_threshold: int = Field(default=3, ge=1, le=100)
    circuit_reset_seconds: float = Field(default=30.0, ge=1, le=3600)

    reranker_provider: Literal["heuristic", "cross_encoder"] = "heuristic"
    cross_encoder_model: str = "BAAI/bge-reranker-v2-m3"
    web_search_provider: Literal["disabled", "searxng"] = "disabled"
    searxng_base_url: str = "http://localhost:8080"

    generation_self_score_threshold: float = Field(default=0.90, ge=0, le=1)
    generation_post_audit_threshold: float = Field(default=0.90, ge=0, le=1)
    generation_min_grounding_coverage: float = Field(default=0.15, ge=0, le=1)
    generation_min_evidence_score: float = Field(default=0.35, ge=0, le=1)
    generation_min_query_coverage: float = Field(default=0.35, ge=0, le=1)
    generation_max_tokens: int = Field(default=800, ge=64, le=32768)
    generation_store_records: bool = True

    slo_availability_target: float = Field(default=0.99, gt=0, le=1)
    slo_p95_latency_ms: float = Field(default=2000, gt=0, le=60000)
    slo_answer_success_target: float = Field(default=0.90, ge=0, le=1)

    @model_validator(mode="after")
    def validate_chunk_window(self) -> "Settings":
        if self.chunk_overlap_chars >= self.chunk_max_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_max_chars")
        if self.environment == "production":
            api_key = self.api_key.get_secret_value() if self.api_key else ""
            if len(api_key) < 16:
                raise ValueError("RAG_API_KEY must contain at least 16 characters in production")
            hosts = {host.strip() for host in self.trusted_hosts.split(",") if host.strip()}
            if not hosts or "*" in hosts:
                raise ValueError("RAG_TRUSTED_HOSTS must be explicit in production")
            if str(self.database_path) == ":memory:":
                raise ValueError("RAG_DATABASE_PATH cannot use an in-memory database in production")
            if not self.database_path.is_absolute():
                raise ValueError("RAG_DATABASE_PATH must be absolute in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

