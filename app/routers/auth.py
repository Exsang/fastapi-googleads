# app/routers/auth.py
from __future__ import annotations

import os
from urllib.parse import urlsplit
from fastapi import APIRouter, Response, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from google.oauth2.credentials import Credentials

from ..settings import settings  # Pydantic settings singleton
from ..services.oauth import build_flow, save_refresh_token
from ..services.usage_log import log_api_usage

router = APIRouter(tags=["auth"])


def _get_api_key() -> str | None:
    return settings.DASH_API_KEY or None


def _public_base(request: Request) -> str:
    """
    Prefer explicit PUBLIC_BASE_URL; else honor proxy headers; fallback to request.base_url.
    This avoids localhost in Codespaces/ngrok and stabilizes OAuth redirect URIs.
    """
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/")

    xf_host = request.headers.get("x-forwarded-host")
    xf_proto = request.headers.get("x-forwarded-proto") or "https"
    if xf_host:
        return f"{xf_proto}://{xf_host}"

    return str(request.base_url).rstrip("/")


@router.get("/login")
def login_set_cookie(key: str, response: Response):
    api_key = _get_api_key()

    if not api_key:
        return {"status": "dev", "message": "DASH_API_KEY not set; auth disabled."}

    if key != api_key:
        raise HTTPException(status_code=401, detail="Invalid key")

    secure_cookie = os.getenv("COOKIE_SECURE", "0") in ("1", "true", "True")

    response.set_cookie(
        key="dash_auth",
        value=api_key,
        max_age=24 * 3600,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
    )
    return {"status": "ok", "message": "Authenticated. Cookie set for 24h."}


# /auth/start
@router.get("/start")
def auth_start(request: Request):
    try:
        base = _public_base(request)
        redirect_uri = f"{base}/auth/callback"
        flow = build_flow(redirect_uri=redirect_uri)

        # Optional account preselect: /auth/start?email=you@example.com
        login_hint = request.query_params.get("email")

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="select_account consent",   # force account chooser + consent
            include_granted_scopes="true",     # must be *string* "true"
            login_hint=login_hint,
        )
        return RedirectResponse(auth_url)
    except Exception as e:
        return JSONResponse({"step": "auth_start", "error": str(e)}, status_code=500)


# /auth/callback
@router.get("/callback")
def auth_callback(request: Request):
    try:
        base = _public_base(request)
        expected_redirect = f"{base}/auth/callback"
        url_str = str(request.url)

        if "code=" not in url_str:
            return JSONResponse(
                {
                    "step": "auth_callback",
                    "error": "Missing authorization code in callback. Start at /auth/start and approve the consent screen.",
                    "received_url": url_str,
                    "expected_redirect_uri": expected_redirect,
                },
                status_code=400,
            )

        # Build the SAME redirect_uri used on /auth/start
        flow = build_flow(redirect_uri=expected_redirect)

        # *** Critical fix: do NOT redirect the browser. Instead, reconstruct the
        # authorization_response on the correct host but keep the exact querystring
        # (code, state, scope). This avoids proxy/localhost redirect loops.
        parts = urlsplit(url_str)
        fixed_auth_response = f"{expected_redirect}?{parts.query}"

        # Exchange code for tokens
        flow.fetch_token(authorization_response=fixed_auth_response)
        creds: Credentials = flow.credentials
        if not creds.refresh_token:
            return JSONResponse(
                {"error": "No refresh token returned. Try again; ensure prompt=consent and approve access."},
                status_code=400,
            )

        save_refresh_token(creds.refresh_token)

        log_api_usage(
            scope_id="oauth",
            request_id=None,
            endpoint="/auth/callback",
            request_type="other",
            operations=0,
        )
        return JSONResponse({"status": "ok", "message": "Refresh token saved. You can now hit /ads/customers."})
    except Exception as e:
        return JSONResponse({"step": "auth_callback", "error": str(e)}, status_code=500)


# Helpful diagnostic endpoint
@router.get("/debug")
def auth_debug(request: Request):
    base = _public_base(request)
    redirect_uri = f"{base}/auth/callback"
    return {
        "computed_redirect_uri": redirect_uri,
        "client_id_tail": (settings.GOOGLE_ADS_CLIENT_ID[-16:] if settings.GOOGLE_ADS_CLIENT_ID else None),
        "host": request.headers.get("host"),
        "x_forwarded_host": request.headers.get("x-forwarded-host"),
        "x_forwarded_proto": request.headers.get("x-forwarded-proto"),
        "public_base_env": settings.PUBLIC_BASE_URL,
        "note": "Ensure computed_redirect_uri is listed in your OAuth client's Authorized redirect URIs and the client_id matches your Codespaces env.",
    }
