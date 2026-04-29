import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    db_host: str = "in-mum-web946.main-hosting.eu"
    db_port: int = 3306
    db_name: str = "u678535045_devita_dev_db"
    db_user: str = "u678535045_devita_dev_db"
    db_password: str = "PNYS*;Op7"

    # LLM provider: "mistral"
    ai_provider: str = "mistral"

    # Mistral
    mistral_api_key: str = "Chcu1jvd9ewzHmDlp70R4hzGg5nxusdl"
    mistral_base_url: str = "https://api.mistral.ai/v1"
    mistral_model: str = "mistral-large-latest"

    # LLM tuning
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048

    # Schema caching
    schema_cache_ttl: int = 86400  # 1 day in seconds

    # Extra environment variables (to avoid validation errors)
    database_url: str = ""
    mysql_ssl_disabled: str = "false"
    app_env: str = "production"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()