# app/routers/googleads_proxy.py
"""
API-key protected proxy endpoints for Google Ads API, designed for use by GPT Actions
(or any other trusted client). Keeps Google credentials server-side.

Endpoints:
- POST /proxy/googleads/customers/{customer_id}/search
    Body: {"query": "<GAQL>"}  -> Proxies to searchStream
    Optional Header: X-Login-Customer-Id: <MCC/manager id>

- GET /proxy/googleads/customers/{customer_id}/assets
    Simple prebuilt GAQL example to demonstrate constrained queries.

Security:
- Uses your existing API key dependency from app.deps.auth.api_key_auth
"""

from typing import Dict, Optional, Any, List
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
import requests

from app.deps.auth import api_key_auth
from app.services.google_ads_token import (
    get_access_token_from_refresh,
    GoogleAdsAuthError,
)
from app import settings


router = APIRouter()


# ---------- Models ----------

class SearchRequest(BaseModel):
    query: str = Field(..., description="GAQL query to execute via searchStream")


# ---------- Helpers ----------

def _normalize_cid(cid: Optional[str]) -> str:
    """Strip dashes; Google accepts digits only for these headers."""
    return (cid or "").replace("-", "")


def _ads_headers(access_token: str, login_customer_id: Optional[str]) -> Dict[str, str]:
    dev_token = settings.GOOGLE_ADS_DEVELOPER_TOKEN
    if not dev_token:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_ADS_DEVELOPER_TOKEN is not configured.",
        )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": dev_token,
        "Content-Type": "application/json",
    }

    # Prefer per-request header; otherwise fall back to configured MCC/manager id.
    lcid = _normalize_cid(login_customer_id) or _normalize_cid(
        settings.GOOGLE_ADS_MCC_LOGIN_CUSTOMER_ID
    )
    if lcid:
        headers["login-customer-id"] = lcid

    return headers


def _api_base() -> str:
    # Defaults to v18; override via GOOGLE_ADS_API_BASE if needed.
    return settings.GOOGLE_ADS_API_BASE.rstrip("/")


def _search_stream_url(customer_id: str) -> str:
    # NOTE: correct path includes "googleAds:searchStream"
    cid = _normalize_cid(customer_id)
    return f"{_api_base()}/customers/{cid}/googleAds:searchStream"


# ---------- Routes ----------

@router.post("/googleads/customers/{customer_id}/search")
def search_google_ads(
    customer_id: str,
    body: SearchRequest,
    # Custom header name must preserve dashes (no underscore conversion):
    x_login_customer_id: Optional[str] = Header(default=None, convert_underscores=False),
    _: str = Depends(api_key_auth),
):
    """
    Generic proxy to Google Ads searchStream. Returns the raw stream response (list of chunks).
    """
    try:
        access_token = get_access_token_from_refresh()
    except GoogleAdsAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    url = _search_stream_url(customer_id)
    headers = _ads_headers(access_token, x_login_customer_id)

    try:
        resp = requests.post(url, headers=headers, json={"query": body.query}, timeout=120)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Upstream request error: {e}")

    if resp.status_code >= 400:
        # Pass through Google Ads error payload for easier debugging in the client.
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    # searchStream returns an array of JSON objects (chunks). We just relay it.
    return resp.json()


@router.get("/googleads/customers/{customer_id}/assets")
def example_assets_list(
    customer_id: str,
    page_size: int = Query(default=50, ge=1, le=10000),
    _: str = Depends(api_key_auth),
):
    """
    Example constrained query. Helpful when you want to give GPT a safe, narrow endpoint.
    """
    try:
        access_token = get_access_token_from_refresh()
    except GoogleAdsAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    gaql = f"""
      SELECT
        asset.id,
        asset.name,
        asset.type,
        asset.source,
        asset.youtube_video_asset.youtube_video_id
      FROM asset
      LIMIT {page_size}
    """.strip()

    url = _search_stream_url(customer_id)
    headers = _ads_headers(access_token, login_customer_id=None)

    try:
        resp = requests.post(url, headers=headers, json={"query": gaql}, timeout=120)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Upstream request error: {e}")

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    return resp.json()
