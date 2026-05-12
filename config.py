from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    database_url: str
    tavily_api_key: str
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    llm_provider: str = "deepseek"
    jina_api_key: str = ""
    environment: str = "development"
    port: int = 8765
    log_level: str = "INFO"

    # asyncpg pool sizing
    db_pool_min: int = 2
    db_pool_max: int = 10

    # Semantic query cache (Phase A3) — off by default during dev to avoid stale answers
    semantic_cache_enabled: bool = False
    semantic_cache_sim_threshold: float = 0.92
    semantic_cache_ttl_hours: int = 2
    semantic_cache_lookup_timeout_ms: int = 1500

    # Conversation history bounds (Phase A4)
    history_max_turns: int = 4
    history_max_chars: int = 2000

    # LangSmith tracing — read directly via env, mirrored here for visibility
    langsmith_tracing: bool = False
    langsmith_project: str = "weblens"

    # Public mode (anon-session pattern from AlphaLens). When True:
    #   • GET /api/sessions returns [] (sidebar empty for end-users)
    #   • frontend uses sessionStorage for the session_id (cleared on tab close)
    # Sessions still persist in DB for analytics/debugging; they're just not
    # listable via the public API.
    # Set PUBLIC_MODE=true in production; leave false in development so the
    # dev can see all chats in the sidebar.
    public_mode: bool = False

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")


settings = Settings()
