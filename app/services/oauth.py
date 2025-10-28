import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from ..settings import CLIENT_JSON_PATH, SCOPES, REDIRECT_URI, REFRESH_TOKEN_PATH

def _load_client_config() -> dict:
    from pathlib import Path
    p = Path(CLIENT_JSON_PATH)
    if not p.exists():
        raise FileNotFoundError(f"OAuth client JSON not found at {p.resolve()}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    if "web" not in cfg or "client_id" not in cfg["web"] or "client_secret" not in cfg["web"]:
        raise RuntimeError("Invalid OAuth client JSON. Must be a 'Web application' client (key 'web').")
    return cfg

def build_flow() -> Flow:
    cfg = _load_client_config()
    return Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=REDIRECT_URI)

def save_refresh_token(token: str) -> None:
    REFRESH_TOKEN_PATH.write_text(token.strip(), encoding="utf-8")

def read_refresh_token() -> str | None:
    if REFRESH_TOKEN_PATH.exists():
        val = REFRESH_TOKEN_PATH.read_text(encoding="utf-8").strip()
        if val:
            return val
    env_val = __import__("os").getenv("GOOGLE_ADS_REFRESH_TOKEN", "").strip()
    return env_val or None
