"""App settings, read from environment variables (and a .env file when running locally).

Why pydantic-settings: every setting is typed and validated at startup, so a typo'd
or missing variable fails loudly on boot instead of deep inside a request.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),  # works from backend/ (venv) or project root
        extra="ignore",
    )

    app_name: str = "ComplianceIQ"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql://complianceiq:complianceiq@localhost:5432/complianceiq"
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    redis_url: str = "redis://localhost:6379/0"

    # Retrieval (ADR-005: local bge-m3 on the GPU). The slim Docker image has no torch, so it sets this false.
    load_embedder: bool = True
    embed_device: str = "cuda"
    top_k: int = 5                 # parent chunks sent to the LLM
    use_reranker: bool = True      # cross-encoder over the top hybrid candidates (M3); needs ~1.1 GB more VRAM
    retrieval_mode: str = "hybrid_rerank"   # best MRR in the ablation (evals/results/retrieval_report.md)
    min_rerank_score: float = 0.0  # below this top score, refuse without calling the LLM (calibrate from evals)

    # Generation: a local model served by Ollama (ollama.com), e.g. `ollama pull phi4-mini`
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "phi4-mini"
    llm_timeout_s: float = 180.0


@lru_cache
def get_settings() -> Settings:
    """Build settings once and reuse them (env vars don't change while the app runs)."""
    return Settings()
