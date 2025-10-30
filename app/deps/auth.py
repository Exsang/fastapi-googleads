# app/deps/auth.py
from fastapi import Header, HTTPException, status, Cookie
from ..settings import settings

def require_auth(
    x_api_key: str | None = Header(default=None),
    dash_auth: str | None = Cookie(default=None),
) -> None:
    """Accept API key from header OR cookie."""
    expected_key = settings.DASH_API_KEY

    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: DASH_API_KEY not set.",
        )

    supplied = x_api_key or dash_auth
    if supplied != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
