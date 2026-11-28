"""App settings, read from environment variables (and a .env file when running locally).

Why pydantic-settings: every setting is typed and validated at startup, so a typo'd or missing variable
fails loudly on boot instead of deep inside a request. Every field can be overridden with an env var of the
same name in capitals, e.g. RETRIEVAL_MODE=hybrid_rerank.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "ComplianceIQ"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql://complianceiq:complianceiq@localhost:5432/complianceiq"
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10
    redis_url: str = "redis://localhost:6379/0"

    # ---- retrieval (ADR-005, ADR-009) ----
    load_embedder: bool = True     # the slim Docker image has no torch and sets this false
    embed_device: str = "cuda"
    top_k: int = 5                 # paragraphs sent to the LLM
    use_reranker: bool = True      # cross-encoder over the top candidates; needs ~1.1 GB more VRAM
    # Ablation (evals/results/retrieval_report.md): vector+rerank MRR 0.906 at ~1.0 s vs hybrid+rerank 0.906 at ~2.2 s
    retrieval_mode: str = "vector_rerank"
    # Calibrated on the golden set: keeps 100% of answerable questions, refuses 80% of out-of-scope ones
    rerank_top: int = 20           # candidates the cross-encoder re-scores (fewer = faster on CPU)
    min_rerank_score: float = 0.31

    # ---- query intelligence (M5) ----
    condense_followups: bool = True   # rewrite "what about NBFCs?" into a standalone question using history
    query_expansion: str = "none"     # none | multi_query | hyde  (LLM-based; measured in the ablation)

    # ---- generation (M7 provider chain) ----
    llm_providers: str = "ollama"     # comma-separated fallback order: ollama, openai_compat, bedrock
    llm_model: str = "phi4-mini"      # Ollama model
    ollama_url: str = "http://localhost:11434"
    llm_timeout_s: float = 180.0
    openai_compat_base_url: str = "https://api.groq.com/openai/v1"   # any OpenAI-style API
    openai_compat_api_key: str = ""
    openai_compat_model: str = "llama-3.1-8b-instant"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    aws_region: str = "ap-south-1"
    # USD per 1M tokens [input, output] per provider. Local = 0. Set hosted prices from your provider's page.
    llm_prices_json: str = '{"ollama": [0, 0], "openai_compat": [0.05, 0.08], "bedrock": [0.25, 1.25]}'

    # ---- platform (M7) ----
    auth_required: bool = False       # local dev: anonymous access as role "analyst". Set true when deployed.
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 480
    rate_limit_per_minute: int = 20   # per user (or per IP when anonymous)
    cache_ttl_s: int = 86_400
    semantic_cache_threshold: float = 0.95   # cosine similarity for "same question, different words"


@lru_cache
def get_settings() -> Settings:
    """Build settings once and reuse them (env vars don't change while the app runs)."""
    return Settings()
