import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


ROOT_DIR = Path(__file__).resolve().parents[1]
_load_dotenv(ROOT_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_any(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def _env_bool(name: str, default: str = "false") -> bool:
    return _env(name, default).lower() in {"1", "true", "yes"}


def _is_usable_database_url(value: str) -> bool:
    return bool(value) and "YOUR_" not in value


@dataclass(frozen=True)
class Settings:
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    mysql_ssl_disabled: bool
    database_url: str
    app_env: str
    ai_provider: str
    gemini_api_key: str
    gemini_base_url: str
    gemini_model: str
    groq_api_key: str
    groq_base_url: str
    groq_model: str
    llm_temperature: float
    llm_max_tokens: int

    @property
    def sqlalchemy_url(self) -> str:
        if _is_usable_database_url(self.database_url):
            return self.database_url

        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        host = self.mysql_host
        port = self.mysql_port
        database = quote_plus(self.mysql_database)
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"


def get_settings() -> Settings:
    return Settings(
        mysql_host=_env_any("DB_HOST", "MYSQL_HOST", default="127.0.0.1"),
        mysql_port=int(_env_any("DB_PORT", "MYSQL_PORT", default="3306")),
        mysql_database=_env_any("DB_NAME", "MYSQL_DATABASE", default="devita_project_management"),
        mysql_user=_env_any("DB_USER", "MYSQL_USER", default="root"),
        mysql_password=_env_any("DB_PASSWORD", "MYSQL_PASSWORD", default=""),
        mysql_ssl_disabled=_env_bool("MYSQL_SSL_DISABLED", "true"),
        database_url=_env("DATABASE_URL", ""),
        app_env=_env("APP_ENV", "development"),
        ai_provider=_env("AI_PROVIDER", "gemini").lower(),
        gemini_api_key=_env("GEMINI_API_KEY", ""),
        gemini_base_url=_env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/"),
        gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        groq_api_key=_env("GROQ_API_KEY", ""),
        groq_base_url=_env("GROQ_BASE_URL", "https://api.groq.com").rstrip("/"),
        groq_model=_env("GROQ_MODEL", "llama-3.3-70b-versatile"),
        llm_temperature=float(_env("LLM_TEMPERATURE", "0.1")),
        llm_max_tokens=int(_env("LLM_MAX_TOKENS", "2500")),
    )
