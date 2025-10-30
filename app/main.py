# app/main.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

# ---------------------------------------------------------------------
# Load environment variables before imports that depend on them
# ---------------------------------------------------------------------
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
except Exception:
    pass  # If dotenv isn't installed, continue using system env only

# ---------------------------------------------------------------------
# Imports (load after .env)
# ---------------------------------------------------------------------
from .settings import APP_TITLE  # noqa: E402
from .routers.auth import router as auth_router  # noqa: E402
from .routers.ads import router as ads_router  # noqa: E402
from .routers.usage import router as usage_router  # noqa: E402
from .routers.misc import router as misc_router  # noqa: E402

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
logger = logging.getLogger("fastapi-googleads")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

# ---------------------------------------------------------------------
# Lifespan (startup/shutdown)
# ---------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FastAPI + Google Ads service")

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

    yield  # --- Application runs here ---

    logger.info("Shutting down FastAPI + Google Ads service")

# ---------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------
APP = FastAPI(
    title=APP_TITLE,
    version=os.environ.get("APP_VERSION", "0.1.0"),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------
# CORS (liberal defaults for dev; tighten in prod)
# ---------------------------------------------------------------------
cors_origins = os.environ.get("FASTAPI_CORS_ORIGINS", "*")
allow_origins = [o.strip() for o in cors_origins.split(",")] if cors_origins else ["*"]

APP.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@APP.get("/health")
def health():
    return {"status": "ok"}

# Redirect root → dashboard
@APP.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/misc/")

# Register routers
APP.include_router(auth_router, prefix="/auth", tags=["auth"])
APP.include_router(ads_router, prefix="/ads", tags=["google-ads"])
APP.include_router(usage_router, prefix="/usage", tags=["usage"])
APP.include_router(misc_router, prefix="/misc", tags=["misc"])

__all__ = ["APP"]
