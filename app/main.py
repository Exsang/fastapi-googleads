# app/main.py
from __future__ import annotations
from starlette.responses import RedirectResponse
from app.routers import googleads_proxy
from fastapi.responses import RedirectResponse

import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime
from sqlalchemy import text as _sql_text

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse, HTMLResponse

# Prefer Starlette's ProxyHeadersMiddleware; fallback to Uvicorn if unavailable
try:
    from starlette.middleware.proxy_headers import ProxyHeadersMiddleware  # Starlette ≥ 0.27
except Exception:  # pragma: no cover
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # Fallback

# ---------------------------------------------------------------------
# Load environment variables (repo .env only; Codespaces secrets come from env)
# ---------------------------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore
    repo_env = Path(__file__).resolve().parents[1] / ".env"
    if repo_env.exists():
        load_dotenv(repo_env, override=True)
except Exception:
    # If python-dotenv isn't installed, proceed with system env (Codespaces secrets)
    pass

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

    # Warn if core env vars are missing; rely on Codespaces secrets or local .env
    required_env = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "LOGIN_CUSTOMER_ID",
    ]
    missing = [k for k in required_env if not os.environ.get(k)]
    if missing:
        logger.warning("Missing environment variables: %s", ", ".join(missing))

    # Helpful hint for Assist API
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning(
            "OPENAI_API_KEY is not set; /assist/chat will return an auth/config error.")

    # ---------------------------------------------------------------
    # Optional background re-embed freshness loop
    # ---------------------------------------------------------------
    try:
        # local import to avoid early load
        from app.services.embeddings import reembed_stale
    except Exception:
        reembed_stale = None  # type: ignore

    reembed_enabled = os.getenv("REEMBED_ENABLED", "true").lower() in {
        "1", "true", "yes"}
    interval_minutes = int(os.getenv("REEMBED_INTERVAL_MINUTES", "0") or 0) or (
        # default 6h
        60 * int(os.getenv("REEMBED_INTERVAL_HOURS", "0") or 0)) or 360
    reembed_limit = int(os.getenv("REEMBED_LIMIT", "150"))
    reembed_entity_type = os.getenv("REEMBED_ENTITY_TYPE")  # optional filter
    reembed_scope_id = os.getenv("REEMBED_SCOPE_ID")  # optional CID filter
    max_age_hours = int(os.getenv("REEMBED_MAX_AGE_HOURS", "24"))

    # ---------------------------------------------------------------
    # Optional pgvector ANALYZE loop (index/statistics maintenance)
    # ---------------------------------------------------------------
    analyze_enabled = os.getenv("PGVECTOR_ANALYZE_ENABLED", "false").lower() in {
        "1", "true", "yes"}
    analyze_interval_minutes = int(os.getenv("PGVECTOR_ANALYZE_INTERVAL_MINUTES", "0") or 0) or (
        # default daily
        60 * int(os.getenv("PGVECTOR_ANALYZE_INTERVAL_HOURS", "0") or 0)) or 1440
    analyze_reindex = os.getenv("PGVECTOR_ANALYZE_REINDEX", "false").lower() in {
        "1", "true", "yes"}

    async def _analyze_loop():
        if not analyze_enabled:
            logger.info("pgvector analyze loop disabled")
            return
        logger.info("Starting pgvector analyze loop: every %d min (reindex=%s)",
                    analyze_interval_minutes, analyze_reindex)
        try:
            while True:
                try:
                    # Direct SQL; Postgres only. Silently skip on other dialects.
                    from app.db.session import engine as _engine  # local import
                    if _engine.dialect.name == "postgresql":
                        with _engine.connect() as conn:
                            conn = conn.execution_options(
                                isolation_level="AUTOCOMMIT")
                            conn.execute(_sql_text("ANALYZE embedding"))
                            if analyze_reindex:
                                try:
                                    conn.execute(
                                        _sql_text("REINDEX INDEX CONCURRENTLY IF EXISTS ix_embedding_vector_ivfflat"))
                                except Exception as _re:
                                    logger.warning(
                                        "Analyze loop reindex error: %s", _re)
                        logger.info("pgvector analyze tick %s (reindex=%s)",
                                    datetime.utcnow().isoformat(), analyze_reindex)
                    else:
                        logger.info(
                            "pgvector analyze tick skipped (dialect=%s)", _engine.dialect.name)
                except Exception as e:
                    logger.warning("Analyze loop error: %s", e)
                await asyncio.sleep(analyze_interval_minutes * 60)
        except asyncio.CancelledError:
            logger.info("pgvector analyze loop cancelled")

    async def _reembed_loop():
        if not reembed_enabled or reembed_stale is None:
            logger.info("Re-embed loop disabled (enabled=%s, available=%s)",
                        reembed_enabled, bool(reembed_stale))
            return
        logger.info("Starting re-embed freshness loop: every %d min (limit=%d, max_age_hours=%d, entity_type=%s, scope_id=%s)",
                    interval_minutes, reembed_limit, max_age_hours, reembed_entity_type, reembed_scope_id)
        try:
            while True:
                try:
                    summary = reembed_stale(
                        max_age_hours=max_age_hours,
                        limit=reembed_limit,
                        entity_type=reembed_entity_type,
                        scope_id=reembed_scope_id,
                    ) if reembed_stale else {"ok": False, "error": "unavailable"}
                    logger.info("Re-embed tick %s: %s",
                                datetime.utcnow().isoformat(), summary)
                except Exception as e:
                    logger.warning("Re-embed loop error: %s", e)
                await asyncio.sleep(interval_minutes * 60)
        except asyncio.CancelledError:
            logger.info("Re-embed loop cancelled")

    if reembed_enabled and reembed_stale is not None:
        app.state.reembed_task = asyncio.create_task(_reembed_loop())
    else:
        app.state.reembed_task = None

    if analyze_enabled:
        app.state.analyze_task = asyncio.create_task(_analyze_loop())
    else:
        app.state.analyze_task = None

    yield  # --- Application runs here ---

    logger.info("Shutting down FastAPI + Google Ads service")
    # Cancel background task if running
    for _tname in ("reembed_task", "analyze_task"):
        task = getattr(app.state, _tname, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass

# ---------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------
APP = FastAPI(
    title=os.environ.get("APP_TITLE", "Google API Backend"),
    version=os.environ.get("APP_VERSION", "0.1.0"),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

__all__ = ["APP"]

# ---------------------------------------------------------------------
# CORS (liberal defaults for dev; tighten in prod)
# ---------------------------------------------------------------------
cors_origins = os.environ.get("FASTAPI_CORS_ORIGINS", "*")
allow_origins = [o.strip() for o in cors_origins.split(",")
                 ] if cors_origins else ["*"]

APP.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------
# Trust proxy headers (so request.base_url matches forwarded host/proto)
# ---------------------------------------------------------------------
APP.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# ---------------------------------------------------------------------
# Basic routes
# ---------------------------------------------------------------------


@APP.get("/health")
def health():
    return {"status": "ok"}
# app/main.py (add right below your existing /health)


@APP.head("/health")
def health_head():
    return {}


# ---------------------------------------------------------------------
# Root redirect to login page
# ---------------------------------------------------------------------
@APP.get("/", include_in_schema=False)
async def root_redirect(request: Request):
    """
    Redirect root to the login page, which shows auth status and quick links.
    After authentication, users can navigate to /misc/dashboard.
    """
    return RedirectResponse(url="/auth/login-page", status_code=303)


# ---------------------------------------------------------------------
# Router registration (DEFERRED IMPORTS to avoid circular imports)
# ---------------------------------------------------------------------


def _register_routers() -> None:
    """
    Import routers only after APP is created to avoid circular-import issues.
    """
    try:
        # These modules must NOT import app.main
        from app.routers.auth import router as auth_router
        from app.routers.ads import router as ads_router
        from app.routers.usage import router as usage_router
        from app.routers.misc import router as misc_router
    except Exception as e:
        logger.exception("Failed importing core routers: %s", e)
        raise

    # Include core routers
    APP.include_router(auth_router, prefix="/auth", tags=["auth"])
    APP.include_router(ads_router, prefix="/ads", tags=["google-ads"])
    # usage_router already declares prefix="/ads"; include without extra prefix
    APP.include_router(usage_router)
    APP.include_router(misc_router)  # misc defines its own prefix="/misc"

    # Optional/extended routers (keep each import isolated to avoid cycles)
    try:
        from app.routers import assist
        # defines its own prefix (e.g., "/assist")
        APP.include_router(assist.router)
    except Exception as e:
        logger.warning("Skipping assist router due to import error: %s", e)

    try:
        from app.routers import ops_patch
        APP.include_router(ops_patch.router)  # defines its own prefix "/ops"
    except Exception as e:
        logger.warning("Skipping ops_patch router due to import error: %s", e)

    # Read-only filesystem/code endpoints
    try:
        from app.routers import ops_fs
        APP.include_router(ops_fs.router)  # prefix "/ops"
    except Exception as e:
        logger.warning("Skipping ops_fs router due to import error: %s", e)

    # Archive export endpoint (.tar.gz)
    try:
        from app.routers import ops_archive
        APP.include_router(ops_archive.router)  # prefix "/ops"
    except Exception as e:
        logger.warning(
            "Skipping ops_archive router due to import error: %s", e)

    # DB ops (Neon connectivity tests)
    try:
        from app.routers import ops_db
        APP.include_router(ops_db.router)
    except Exception as e:
        logger.warning("Skipping ops_db router due to import error: %s", e)

    # ETL endpoints (secured)
    try:
        from app.routers import etl
        APP.include_router(etl.router)
    except Exception as e:
        logger.warning("Skipping etl router due to import error: %s", e)

    # Agents endpoints (proposal/approval workflow)
    try:
        from app.routers import agents
        APP.include_router(agents.router)
    except Exception as e:
        logger.warning("Skipping agents router due to import error: %s", e)


# Register at import time
_register_routers()


# Proxy router included after main registration
APP.include_router(googleads_proxy.router, prefix="/proxy", tags=["proxy"])

# Note: root "/" route defined earlier redirects to /login-page for secure access flow
