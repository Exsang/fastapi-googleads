# app/settings.py
from __future__ import annotations

from pathlib import Path
import os

# pydantic v2+ moved BaseSettings to pydantic-settings; import compatibly.
USING_PYDANTIC_V2 = False
try:
    from pydantic_settings import BaseSettings
    USING_PYDANTIC_V2 = True
except Exception:
    from pydantic import BaseSettings

# Load .env early if python-dotenv is available
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
except Exception:
    pass


class Settings(BaseSettings):
    DASH_API_KEY: str | None = None
    DATABASE_URL: str | None = None
    GOOGLE_ADS_CLIENT_ID: str | None = None
    GOOGLE_ADS_CLIENT_SECRET: str | None = None
    GOOGLE_ADS_REFRESH_TOKEN: str | None = None
    GOOGLE_ADS_DEVELOPER_TOKEN: str | None = None
    LOGIN_CUSTOMER_ID: str | None = None
    DEFAULT_MCC_ID: str | None = None
    PUBLIC_BASE_URL: str | None = None
    BASIC_DAILY_GET_REQUEST_LIMIT: int = 15000
    BASIC_DAILY_OPERATION_LIMIT: int = 10000

    # pydantic v2 vs v1 config
    if USING_PYDANTIC_V2:
        model_config = {
            "env_file": ".env",
            "env_file_encoding": "utf-8",
            "extra": "ignore",  # ignore unrelated env vars (host/port/etc.)
        }
    else:
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"


# single shared instance (both names used across the codebase)
settings = Settings()
SETTINGS = settings

# Backwards-compatible module-level constant for legacy imports
DEFAULT_MCC_ID = (
    settings.DEFAULT_MCC_ID
    or os.environ.get("DEFAULT_MCC_ID")
    or "7414394764"
)
