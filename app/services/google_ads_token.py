# app/services/google_ads_token.py
"""
Small helper to mint short-lived Google OAuth access tokens for the Google Ads API
using a stored refresh token from environment variables (Codespaces secrets).
"""

from typing import Final
import os
import requests

from app import settings  # reads env via os.getenv in your project

TOKEN_URL: Final[str] = "https://oauth2.googleapis.com/token"


class GoogleAdsAuthError(Exception):
    """Raised when we fail to exchange the refresh token for an access token."""
    pass


def _require_nonempty(name: str, value: str) -> None:
    if not value:
        raise GoogleAdsAuthError(
            f"Missing required environment variable: {name}. "
            "Ensure this is set in Codespaces secrets and your app has access to it."
        )


def get_access_token_from_refresh() -> str:
    """
    Exchanges the configured refresh token for a short-lived OAuth access token.
    Returns:
        access_token (str)
    Raises:
        GoogleAdsAuthError on configuration or HTTP errors.
    """
    # Validate presence of required secrets (they come from Codespaces env vars).
    _require_nonempty("GOOGLE_ADS_CLIENT_ID", settings.GOOGLE_ADS_CLIENT_ID)
    _require_nonempty("GOOGLE_ADS_CLIENT_SECRET", settings.GOOGLE_ADS_CLIENT_SECRET)
    _require_nonempty("GOOGLE_ADS_REFRESH_TOKEN", settings.GOOGLE_ADS_REFRESH_TOKEN)

    data = {
        "grant_type": "refresh_token",
        "client_id": settings.GOOGLE_ADS_CLIENT_ID,
        "client_secret": settings.GOOGLE_ADS_CLIENT_SECRET,
        "refresh_token": settings.GOOGLE_ADS_REFRESH_TOKEN,
    }

    try:
        resp = requests.post(TOKEN_URL, data=data, timeout=30)
    except requests.RequestException as e:
        raise GoogleAdsAuthError(f"HTTP error refreshing token: {e}") from e

    if resp.status_code != 200:
        # Bubble up the token server error for debugging
        raise GoogleAdsAuthError(
            f"Failed to refresh token (status {resp.status_code}): {resp.text}"
        )

    token = resp.json().get("access_token")
    if not token:
        raise GoogleAdsAuthError("Token endpoint succeeded but returned no access_token.")
    return token
