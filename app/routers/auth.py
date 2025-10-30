# app/routers/auth.py
from __future__ import annotations

import os
from fastapi import APIRouter, Response, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from google.oauth2.credentials import Credentials

from ..settings import settings  # <-- use the pydantic settings singleton
from ..services.oauth import build_flow, save_refresh_token
from ..services.usage_log import log_api_usage

router = APIRouter(tags=["auth"])

def _get_api_key() -> str | None:
    return settings.DASH_API_KEY or None

@router.get("/login")
def login_set_cookie(key: str, response: Response):
    api_key = _get_api_key()

    # If no API key configured, report dev mode
    if not api_key:
        return {"status": "dev", "message": "DASH_API_KEY not set; auth disabled."}

    if key != api_key:
        raise HTTPException(status_code=401, detail="Invalid key")

    # In dev over HTTP, secure=False. If using HTTPS (e.g., ngrok), set secure=True.
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

@router.get("/auth/start")
def auth_start():
    try:
        flow = build_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        return RedirectResponse(auth_url)
    except Exception as e:
        return JSONResponse({"step": "auth_start", "error": str(e)}, status_code=500)

@router.get("/auth/callback")
def auth_callback(request: Request):
    try:
        flow = build_flow()
        flow.fetch_token(authorization_response=str(request.url))
        creds: Credentials = flow.credentials
        if not creds.refresh_token:
            return JSONResponse(
                {
                    "error": "No refresh token returned. Try again; ensure prompt=consent and approve access."
                },
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
