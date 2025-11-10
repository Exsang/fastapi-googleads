# app/routers/auth.py
from __future__ import annotations

import os
from urllib.parse import urlsplit
from fastapi import APIRouter, Response, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from google.oauth2.credentials import Credentials

from ..settings import settings  # Pydantic settings singleton
from ..services.oauth import build_flow, save_refresh_token
from ..services.usage_log import record_quota_event

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


# /login — browser-friendly login page
@router.get("/login-page", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    """
    Browser-friendly login form. Submits to /login with ?key=...
    Shows current auth status and provides quick one-click login for dev.
    """
    base = _public_base(request)
    api_key = _get_api_key()

    # Check if already authenticated via cookie
    cookie_key = request.cookies.get("dash_auth")
    is_authed = cookie_key and api_key and cookie_key == api_key

    auth_status_html = ""
    if is_authed:
        auth_status_html = '''
        <div class="rounded-lg border border-green-200 bg-green-50 p-4 mb-6">
          <div class="flex items-center">
            <svg class="h-5 w-5 text-green-600 mr-2" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
            </svg>
            <span class="font-semibold text-green-900">Already authenticated</span>
          </div>
          <p class="text-sm text-green-700 mt-2">Your session is active. You can access all protected endpoints.</p>
        </div>
        '''
    elif not api_key:
        auth_status_html = '''
        <div class="rounded-lg border border-yellow-200 bg-yellow-50 p-4 mb-6">
          <div class="flex items-center">
            <svg class="h-5 w-5 text-yellow-600 mr-2" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
            <span class="font-semibold text-yellow-900">Development Mode</span>
          </div>
          <p class="text-sm text-yellow-700 mt-2">DASH_API_KEY is not set. Authentication is disabled.</p>
        </div>
        '''

    # Dev convenience: show a quick-login button if in local/codespaces and key is present
    dev_login_html = ""
    if api_key and not is_authed:
        # Only show in obvious dev environments
        host = request.headers.get("host", "")
        is_dev = any(x in host for x in [
                     "localhost", "127.0.0.1", "github.dev", "gitpod.io"])
        if is_dev:
            dev_login_html = f'''
            <div class="mb-6 rounded-lg border border-blue-200 bg-blue-50 p-4">
              <p class="text-sm text-blue-900 font-semibold mb-2">Quick Dev Login</p>
              <p class="text-xs text-blue-700 mb-3">Click below to auto-authenticate with your configured API key (dev environments only).</p>
              <a href="/auth/login?key={api_key}"
                 class="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition">
                <svg class="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                </svg>
                Authenticate Now
              </a>
            </div>
            '''

    links_html = f'''
    <div class="space-y-2">
      <a href="{base}/misc/dashboard" class="block px-4 py-2 bg-slate-100 hover:bg-slate-200 rounded-lg text-sm transition">
        📊 Dashboard
      </a>
      <a href="{base}/docs" class="block px-4 py-2 bg-slate-100 hover:bg-slate-200 rounded-lg text-sm transition">
        📖 API Docs (Swagger)
      </a>
      <a href="{base}/ads/customers" class="block px-4 py-2 bg-slate-100 hover:bg-slate-200 rounded-lg text-sm transition">
        🔍 List Customers
      </a>
    </div>
    '''

    return HTMLResponse(f'''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Login — Google Ads API</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 min-h-screen flex items-center justify-center p-4">
  <div class="w-full max-w-md">
    <div class="bg-white rounded-2xl shadow-lg p-8">
      <h1 class="text-2xl font-bold text-slate-900 mb-2">Google Ads API Gateway</h1>
      <p class="text-sm text-slate-600 mb-6">Secure access to your advertising data</p>

      {auth_status_html}
      {dev_login_html}

      <div class="border-t border-slate-200 pt-6">
        <h2 class="text-sm font-semibold text-slate-700 mb-3">Quick Links</h2>
        {links_html}
      </div>

      <div class="mt-6 pt-6 border-t border-slate-200 text-xs text-slate-500 text-center">
        API key authentication • Session valid 24h
      </div>
    </div>
  </div>
</body>
</html>
    ''')


@router.get("/login")
def login_set_cookie(key: str, request: Request):
    api_key = _get_api_key()

    if not api_key:
        return {"status": "dev", "message": "DASH_API_KEY not set; auth disabled."}

    if key != api_key:
        raise HTTPException(status_code=401, detail="Invalid key")

    # Redirect to dashboard or referring page after successful login
    redirect_to = request.query_params.get("redirect", "/misc/dashboard")
    response = RedirectResponse(url=redirect_to, status_code=303)

    secure_cookie = os.getenv("COOKIE_SECURE", "0") in ("1", "true", "True")
    response.set_cookie(
        key="dash_auth",
        value=api_key,
        max_age=24 * 3600,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
    )

    return response


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

        # record an internal API request for successful callback
        try:
            record_quota_event("internal_api", "requests", 1,
                               scope_id="oauth", endpoint="/auth/callback")
        except Exception:
            pass
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
