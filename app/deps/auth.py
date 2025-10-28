from typing import Optional
from fastapi import Depends, Cookie, Query, Header, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from ..settings import API_KEY

auth_scheme = HTTPBearer(auto_error=False)

def require_auth(
    creds: HTTPAuthorizationCredentials = Depends(auth_scheme),
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key", convert_underscores=False),
    dash_auth: Optional[str] = Cookie(default=None),
    key_qs: Optional[str] = Query(default=None, alias="key"),
):
    # If no API key configured, run in dev mode (no auth)
    if not API_KEY:
        return

    presented = None
    if creds and creds.scheme and creds.credentials and creds.scheme.lower() == "bearer":
        presented = creds.credentials
    if not presented and x_api_key:
        presented = x_api_key
    if not presented and dash_auth:
        presented = dash_auth
    if not presented and key_qs:
        presented = key_qs

    if presented != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
