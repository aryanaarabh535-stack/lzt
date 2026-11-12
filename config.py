from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


BASE_DIR = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE_DIR / "sessions"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "autobuyer.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    owner_id: int
    ids_channel_id: int

    api_id: int
    api_hash: str

    lzt_token: str
    lzt_proxy: str | None = None

    daily_budget_usd: float = 1.0
    total_budget_usd: float = 50.0
    capacity_poll_seconds: int = 300
    lzt_scan_seconds: int = 20
    buy_multiplier: float = 0.5

    default_session_days: int = 1
    default_password: str = "no"
    default_login_mail: str = "yes"
    default_spam_block: str = "no"

    timezone: str = "UTC"
    log_level: str = "INFO"

    grok_api_key: str | None = None  # optional xAI key
    gemini_api_key: str | None = None  # optional Google Gemini key (fallback)


def get_settings() -> Settings:
    return Settings()
