from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_secret: str = "change-me"
    basic_auth_user: str = "admin"
    basic_auth_password: str = "change-me"

    database_path: str = str(ROOT / "data" / "sec_news.db")
    sources_path: str = str(ROOT / "app" / "sources.yaml")

    fetch_interval_hours: int = 4
    translate_enabled: bool = True
    translate_provider: str = "mymemory"
    mymemory_email: str = ""
    translate_max_chars: int = 400
    hide_legislation_by_default: bool = True
    retention_days: int = 7

    # Telegram (optional)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_alerts_enabled: bool = True
    telegram_alert_min_score: float = 75.0
    telegram_digest_enabled: bool = True
    telegram_digest_hour_utc: int = 6

    # Hot-article briefs
    brief_enabled: bool = True
    brief_max_chars: int = 280
    brief_min_score: float = 55.0
    brief_max_per_ingest: int = 8


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    updates: dict[str, str] = {}
    db_path = Path(settings.database_path)
    if not db_path.is_absolute():
        updates["database_path"] = str((ROOT / db_path).resolve())
    sources_path = Path(settings.sources_path)
    if not sources_path.is_absolute():
        updates["sources_path"] = str((ROOT / sources_path).resolve())
    return settings.model_copy(update=updates) if updates else settings
