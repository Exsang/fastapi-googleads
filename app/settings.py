# app/settings.py
from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

# --------------------------------------------------------------------
# Pydantic-based application settings
# --------------------------------------------------------------------
class Settings(BaseSettings):
    # ----------------------------------------------------------------
    # App metadata
    # ----------------------------------------------------------------
    APP_TITLE: str = "Google Ads API Gateway"
    APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0")

        # ----------------------------------------------------------------
    # Secrets and configuration
    # ----------------------------------------------------------------
    DEFAULT_SECRETS_DIR: ClassVar[Path] = Path(r"C:\Users\Coron\Secrets\google_ads")


    DASH_API_KEY: str = os.getenv("DASH_API_KEY", "")

    # ----------------------------------------------------------------
    # Google Ads / OAuth settings
    # ----------------------------------------------------------------
    DEFAULT_MCC_ID: str = os.getenv("DEFAULT_MCC_ID", "7414394764")

    GOOGLE_ADS_LOGIN_CUSTOMER_ID: Optional[str] = os.getenv(
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID"
    ) or os.getenv("LOGIN_CID") or DEFAULT_MCC_ID

    GOOGLE_ADS_DEVELOPER_TOKEN: str = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    GOOGLE_ADS_CLIENT_ID: str = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
    GOOGLE_ADS_CLIENT_SECRET: str = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
    GOOGLE_ADS_REFRESH_TOKEN: str = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")

    GOOGLE_OAUTH_CLIENT_JSON: Path = Path(
        os.getenv(
            "GOOGLE_OAUTH_CLIENT_JSON",
            os.getenv(
                "OAUTH_CLIENT_JSON_PATH",
                str(DEFAULT_SECRETS_DIR / "google_oauth_client.json"),
            ),
        )
    )

    GOOGLE_ADS_REFRESH_TOKEN_FILE: Path = Path(
        os.getenv(
            "GOOGLE_ADS_REFRESH_TOKEN_FILE",
            str(DEFAULT_SECRETS_DIR / "_refresh_token.txt"),
        )
    )

    OAUTH_REDIRECT_URI: str = os.getenv(
        "OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/auth/callback"
    )
    GOOGLE_ADS_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/adwords"
    ]

    # ----------------------------------------------------------------
    # Usage caps (for dashboard or rate limiting)
    # ----------------------------------------------------------------
    BASIC_DAILY_GET_REQUEST_LIMIT: int = int(
        os.getenv("BASIC_DAILY_GET_REQUEST_LIMIT", "1000")
    )
    BASIC_DAILY_OPERATION_LIMIT: int = int(
        os.getenv("BASIC_DAILY_OPERATION_LIMIT", "15000")
    )

    # ----------------------------------------------------------------
    # Server
    # ----------------------------------------------------------------
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # ----------------------------------------------------------------
    # Config
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
