# app/deps/auth.py
import os
from fastapi import Header, HTTPException, status, Cookie, Request, Response
from ..settings import settings

def require_auth(
    request: Request,
    response: Response,
    x_api_key: str | None = Header(default=None),
    dash_auth: str | None = Cookie(default=None),
) -> None:
    """Accept API key from header, Authorization bearer, cookie, or ?key=... in browser."""
    expected_key = settings.DASH_API_KEY

    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: DASH_API_KEY not set.",
        )

    supplied = x_api_key or dash_auth

    # Accept Bearer tokens from Authorization header for convenience
    auth_header = request.headers.get("authorization")
    if auth_header:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token:
            supplied = token
        elif not supplied:
            supplied = auth_header

    # Support one-time ?key=... usage in the browser; set the auth cookie on success
    query_key = request.query_params.get("key")
    if query_key:
        supplied = query_key
        if supplied == expected_key:
            secure_cookie = os.getenv("COOKIE_SECURE", "0") in ("1", "true", "True")
            response.set_cookie(
                key="dash_auth",
                value=expected_key,
                max_age=24 * 3600,
                httponly=True,
                secure=secure_cookie,
                samesite="lax",
            )

    if supplied != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

# app/deps/auth.py
from fastapi import Header, HTTPException
from app import settings

def api_key_auth(authorization: str = Header(None)):
    """
    Simple API key check: Authorization: Bearer <DASH_API_KEY>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    expected = getattr(settings, "DASH_API_KEY", None)
    if not expected:
        raise HTTPException(status_code=500, detail="Server is missing DASH_API_KEY")
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return "ok"
