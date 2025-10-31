# app/services/oauth.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials  # noqa: F401  (kept for type hints/consumers)

from ..settings import settings

# Optional file path (used only if explicitly set via env)
_RAW_PATH = os.getenv("GOOGLE_ADS_REFRESH_TOKEN_FILE")
REFRESH_TOKEN_PATH: Optional[Path] = Path(_RAW_PATH) if _RAW_PATH else None
if REFRESH_TOKEN_PATH:
    REFRESH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)


def _client_config_from_env() -> dict:
    """
    Build a Google OAuth client config from environment variables (Codespaces secrets).
    Avoids reading any external JSON file.
    """
    cid = settings.GOOGLE_ADS_CLIENT_ID
    csec = settings.GOOGLE_ADS_CLIENT_SECRET
    if not cid or not csec:
        raise RuntimeError("Missing GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET in environment.")

    # google_auth_oauthlib expects the 'web' structure for web clients
    return {
        "web": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [],        # provided dynamically at runtime
            "javascript_origins": [],   # not needed here
        }
    }


def build_flow(redirect_uri: str) -> Flow:
    """
    Create an OAuth2 Flow using env-provided client_id/secret and a runtime redirect URI.
    The redirect_uri should be the full URL to /auth/callback on the current host.
    """
    # Ensure no google-ads.yaml path interferes with env-driven config
    os.environ.pop("GOOGLE_ADS_CONFIGURATION_FILE", None)

    client_config = _client_config_from_env()
    return Flow.from_client_config(
        client_config=client_config,
        scopes=settings.GOOGLE_ADS_SCOPES,
        redirect_uri=redirect_uri,
    )


def save_refresh_token(token: str) -> None:
    """
    Persist the refresh token only if a file path is provided via
    GOOGLE_ADS_REFRESH_TOKEN_FILE. In env-only mode, this is a no-op.
    """
    if REFRESH_TOKEN_PATH:
        REFRESH_TOKEN_PATH.write_text(token.strip(), encoding="utf-8")


def read_refresh_token() -> Optional[str]:
    """
    Retrieve the refresh token, preferring the environment variable
    GOOGLE_ADS_REFRESH_TOKEN. If not present and a file path is configured,
    read from that file.
    """
    env_val = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "").strip()
    if env_val:
        return env_val

    if REFRESH_TOKEN_PATH and REFRESH_TOKEN_PATH.exists():
        txt = REFRESH_TOKEN_PATH.read_text(encoding="utf-8").strip()
        return txt or None

    return None
