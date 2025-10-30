# app/settings.py
from __future__ import annotations

import os
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ----------------------------------------------------------------
    # App metadata
    # ----------------------------------------------------------------
    APP_TITLE: str = "Google Ads API Gateway"
    APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0")

    # ----------------------------------------------------------------
    # Auth / API keys (env-only; use Codespaces secrets)
    # ----------------------------------------------------------------
    DASH_API_KEY: str = os.getenv("DASH_API_KEY", "")

    # ----------------------------------------------------------------
    # Google Ads / OAuth settings (env-only; no secrets on disk)
    # ----------------------------------------------------------------
    # Primary MCC / login CID. Prefer LOGIN_CUSTOMER_ID, fall back to defaults/legacy.
    DEFAULT_MCC_ID: str = (
        os.getenv("LOGIN_CUSTOMER_ID")
        or os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
        or os.getenv("LOGIN_CID")
        or os.getenv("DEFAULT_MCC_ID", "7414394764")
    )

    GOOGLE_ADS_DEVELOPER_TOKEN: str = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    GOOGLE_ADS_CLIENT_ID: str = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
    GOOGLE_ADS_CLIENT_SECRET: str = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
    GOOGLE_ADS_REFRESH_TOKEN: str = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")

    # Optional override if you want to pin a specific Ads API surface for logging only.
    GOOGLE_ADS_API_VERSION: str = os.getenv("GOOGLE_ADS_API_VERSION", "auto")

    OAUTH_REDIRECT_URI: str = os.getenv(
        "OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/auth/callback"
    )

    GOOGLE_ADS_SCOPES: List[str] = [
        "https://www.googleapis.com/auth/adwords"
    ]

    # ----------------------------------------------------------------
    # Usage caps (dashboard/rate limiting)
    # ----------------------------------------------------------------
    BASIC_DAILY_GET_REQUEST_LIMIT: int = int(
        os.getenv("BASIC_DAILY_GET_REQUEST_LIMIT", "1000")
    )
    BASIC_DAILY_OPERATION_LIMIT: int = int(
        os.getenv("BASIC_DAILY_OPERATION_LIMIT", "15000")
    )

    # ----------------------------------------------------------------
    # Server / Environment
    # ----------------------------------------------------------------
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    PUBLIC_BASE_URL: Optional[str] = os.getenv("PUBLIC_BASE_URL")

    # ----------------------------------------------------------------
    # Pydantic settings
    # ----------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Instantiate global settings singleton
settings = Settings()

# Re-export key constants for direct imports
APP_TITLE = settings.APP_TITLE
DEFAULT_MCC_ID = settings.DEFAULT_MCC_ID
