# app/main.py
from pathlib import Path
import os

# --- Load environment variables BEFORE importing settings ---
# Priority:
#   1) FASTAPI_GOOGLEADS_ENV (explicit path, if set)
#   2) %USERPROFILE%\Secrets\google_ads\.env
#   3) ./.env (repo root)
try:
    from dotenv import load_dotenv

    REPO_ROOT = Path(__file__).resolve().parents[1]
    repo_env = REPO_ROOT / ".env"

    external_env = os.environ.get(
        "FASTAPI_GOOGLEADS_ENV",
        os.path.expandvars(r"%USERPROFILE%\Secrets\google_ads\.env"),
    )
    external_env_path = Path(external_env)

    if external_env_path.exists():
        load_dotenv(external_env_path, override=True)
    elif repo_env.exists():
        load_dotenv(repo_env, override=True)
    # else: no .env found; rely on process env
except Exception:
    # If python-dotenv isn't installed or any error occurs, continue with process env only.
    pass

# --- FastAPI app & routers ---
from fastapi import FastAPI  # noqa: E402 (import after env load is intentional)

from .settings import APP_TITLE  # noqa: E402
from .routers.auth import router as auth_router  # noqa: E402
from .routers.ads import router as ads_router  # noqa: E402
from .routers.usage import router as usage_router  # noqa: E402
from .routers.misc import router as misc_router  # noqa: E402


APP = FastAPI(title=APP_TITLE)

# Register routers
APP.include_router(auth_router)
APP.include_router(ads_router)
APP.include_router(usage_router)
APP.include_router(misc_router)


# Optional: lightweight health probe
@APP.get("/health")
def health():
    return {"status": "ok"}
