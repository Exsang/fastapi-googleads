from fastapi import APIRouter, Response, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from google.oauth2.credentials import Credentials

from ..settings import API_KEY
from ..services.oauth import build_flow, save_refresh_token
from ..services.usage_log import log_api_usage

router = APIRouter(tags=["auth"])

@router.get("/login")
def login_set_cookie(key: str, response: Response):
    # If no API key configured, report dev mode
    if not API_KEY:
        return {"status": "dev", "message": "DASH_API_KEY not set; auth disabled."}

    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid key")

    response.set_cookie(
        key="dash_auth",
        value=API_KEY,
        max_age=24 * 3600,
        httponly=True,
        secure=False,   # set True if serving via HTTPS (e.g., ngrok)
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
def auth_callback(request):
    try:
        flow = build_flow()
        flow.fetch_token(authorization_response=str(request.url))
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
