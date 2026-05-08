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

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")


settings = Settings()
