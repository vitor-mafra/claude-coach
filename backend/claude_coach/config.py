import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# DATA_DIR is resolved before Settings instantiates so paths derived from it
# (database_url, garmin_tokens_dir) can use it as their default.
_DATA_DIR = Path(os.environ.get("DATA_DIR") or (REPO_ROOT / "data")).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Root for all writable / personal data. On Railway, mount a volume here.
    data_dir: Path = _DATA_DIR

    database_url: str = f"sqlite:///{_DATA_DIR / 'metrics.db'}"
    cors_origins: list[str] = ["http://localhost:5173"]

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    garmin_email: str | None = None
    garmin_password: str | None = None
    garmin_tokens_dir: Path = _DATA_DIR / "garmin_tokens"

    resend_api_key: str | None = None
    resend_from_email: str | None = None
    weekly_report_to_email: str | None = None

    weekly_report_day: str = "monday"
    weekly_report_hour: int = 8
    daily_sync_hour: int = 7
    scheduler_timezone: str = "America/Sao_Paulo"

    # Auth (single-user). When app_password is None, auth is disabled (local dev).
    app_password: str | None = None
    app_session_secret: str | None = None
    auth_cookie_name: str = "cc_session"
    auth_cookie_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 days
    auth_cookie_secure: bool = False  # set True in production
    auth_login_max_attempts: int = 5
    auth_login_window_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
