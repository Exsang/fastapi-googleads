# app/services/oauth.py
import json
from pathlib import Path
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

from ..settings import settings


def _load_client_config() -> dict:
    """Load the OAuth client JSON from the configured secrets directory."""
    p = Path(settings.GOOGLE_OAUTH_CLIENT_JSON)
    if not p.exists():
        raise FileNotFoundError(f"OAuth client JSON not found at {p.resolve()}")

    cfg = json.loads(p.read_text(encoding="utf-8"))
    if "web" not in cfg or "client_id" not in cfg["web"] or "client_secret" not in cfg["web"]:
        raise RuntimeError(
            "Invalid OAuth client JSON. Must be a 'Web application' client (key 'web')."
        )
    return cfg


def build_flow() -> Flow:
    """Create an OAuth flow using the stored client credentials."""
    cfg = _load_client_config()
    return Flow.from_client_config(
        cfg,
        scopes=settings.GOOGLE_ADS_SCOPES,
        redirect_uri=settings.OAUTH_REDIRECT_URI,
    )


def save_refresh_token(token: str) -> None:
    """Write the refresh token to file in the secrets directory."""
    Path(settings.GOOGLE_ADS_REFRESH_TOKEN_FILE).write_text(token.strip(), encoding="utf-8")


def read_refresh_token() -> str | None:
    """Retrieve the saved refresh token or fall back to the environment variable."""
    p = Path(settings.GOOGLE_ADS_REFRESH_TOKEN_FILE)
    if p.exists():
        val = p.read_text(encoding="utf-8").strip()
        if val:
            return val
    env_val = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "").strip()
    return env_val or None
