# app/main.py
from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
import os
import logging

# --- Load environment variables BEFORE importing anything that reads env ---
# Priority:
#   1) FASTAPI_GOOGLEADS_ENV (explicit path, if set)
#   2) %USERPROFILE%\Secrets\google_ads\.env
#   3) ./.env (repo root)
try:
    from dotenv import load_dotenv  # type: ignore

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

# --- FastAPI app & routers (import AFTER env load) ---
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from .settings import APP_TITLE  # noqa: E402
from .routers.auth import router as auth_router  # noqa: E402
from .routers.ads import router as ads_router  # noqa: E402
from .routers.usage import router as usage_router  # noqa: E402
from .routers.misc import router as misc_router  # noqa: E402


# ---- Lifespan (startup/shutdown) -------------------------------------------
logger = logging.getLogger("fastapi-googleads")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Starting FastAPI + Google Ads service")
    # Example: verify required env vars (fail fast in dev if missing)
    required_env = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "DASH_API_KEY",
    ]
    missing = [k for k in required_env if not os.environ.get(k)]
    if missing:
        logger.warning("Missing environment variables: %s", ", ".join(missing))

    # TODO: initialize shared resources here (DB pools, clients, caches)
    # e.g., app.state.db = await init_db_pool()

    yield  # --- Application runs here ---

    # --- Shutdown ---
    logger.info("Shutting down FastAPI + Google Ads service")
    # TODO: gracefully close resources (db connections, clients)
    # e.g., await app.state.db.close()


APP = FastAPI(
    title=APP_TITLE,
    version=os.environ.get("APP_VERSION", "0.1.0"),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# --- CORS (liberal defaults for dev; tighten allow_origins in prod) ---
cors_origins = os.environ.get("FASTAPI_CORS_ORIGINS", "*")
allow_origins = [o.strip() for o in cors_origins.split(",")] if cors_origins else ["*"]

APP.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Health probe ---
@APP.get("/health")
def health():
    return {"status": "ok"}

# --- Register routers with prefixes & tags ---
APP.include_router(auth_router,  prefix="/auth",  tags=["auth"])
APP.include_router(ads_router,   prefix="/ads",   tags=["google-ads"])
APP.include_router(usage_router, prefix="/usage", tags=["usage"])
APP.include_router(misc_router,  prefix="/misc",  tags=["misc"])

__all__ = ["APP"]
