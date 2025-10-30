# app/services/google_ads.py
from __future__ import annotations

import os
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple, Literal

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from ..settings import settings
from .oauth import read_refresh_token  # env + file only (no YAML)

# ------------------------------------------------------------
# API version detection (with env override + probing)
# ------------------------------------------------------------
def _first_importable_version(candidates: List[str]) -> Optional[str]:
    for ver in candidates:
        try:
            __import__(f"google.ads.googleads.{ver}")
            return ver
        except Exception:
            continue
    return None

def _detect_api_version() -> str:
    """
    Pick the newest Ads API version actually available in the installed
    'google-ads' package. If GOOGLE_ADS_API_VERSION is set, use it only if
    it can be imported.
    """
    # Try an explicit override first, but verify it exists.
    forced = os.getenv("GOOGLE_ADS_API_VERSION")
    if forced:
        try:
            __import__(f"google.ads.googleads.{forced}")
            return forced
        except Exception:
            # Fall through to probing if the forced version isn't present
            pass

    # Probe newest → older. Extend this list when upgrading the SDK.
    candidates = ["v20", "v19", "v18", "v17", "v16", "v15"]
    ver = _first_importable_version(candidates)
    if not ver:
        # As a last resort, v17 is a safe default for many installs.
        ver = "v17"
    return ver

_API_VERSION = _detect_api_version()

# ------------------------------------------------------------
# Core client & shared helpers
# ------------------------------------------------------------
def google_ads_client() -> GoogleAdsClient:
    """
    Build a GoogleAdsClient purely from environment-backed settings (Codespaces secrets).
    Force-ignore any google-ads.yaml by unsetting GOOGLE_ADS_CONFIGURATION_FILE.
    Use top-level OAuth keys for broad client-version compatibility.
    """
    # Ensure no YAML file is used implicitly
    os.environ.pop("GOOGLE_ADS_CONFIGURATION_FILE", None)

    # Validate required secrets early
    if not settings.GOOGLE_ADS_DEVELOPER_TOKEN:
        raise RuntimeError("Missing GOOGLE_ADS_DEVELOPER_TOKEN (set in Codespaces secrets).")
    if not settings.GOOGLE_ADS_CLIENT_ID or not settings.GOOGLE_ADS_CLIENT_SECRET:
        raise RuntimeError("Missing GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET (set in Codespaces secrets).")

    refresh_token = read_refresh_token() or settings.GOOGLE_ADS_REFRESH_TOKEN
    if not refresh_token:
        raise RuntimeError(
            "Missing refresh token. Run the OAuth flow at /auth/start to store one, "
            "or set GOOGLE_ADS_REFRESH_TOKEN in Codespaces secrets."
        )

    # Top-level keys (compatible across client versions)
    cfg = {
        "developer_token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        "login_customer_id": settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID,  # optional but recommended for MCC use
        "use_proto_plus": True,
        "client_id": settings.GOOGLE_ADS_CLIENT_ID,
        "client_secret": settings.GOOGLE_ADS_CLIENT_SECRET,
        "refresh_token": refresh_token,
    }

    return GoogleAdsClient.load_from_dict(cfg)

def _get_service_any_version(client: GoogleAdsClient, name: str) -> Tuple[Any, str]:
    """
    Try the pinned _API_VERSION first, then fall back to older versions until one loads.
    Returns (service, version_str). Raises last error if none succeed.
    """
    candidates = [_API_VERSION, "v20", "v19", "v18", "v17", "v16", "v15"]
    seen = set()
    ordered = [v for v in candidates if not (v in seen or seen.add(v))]  # de-dup but keep order

    last_err: Optional[Exception] = None
    for ver in ordered:
        try:
            svc = client.get_service(name, version=ver)
            return svc, ver
        except Exception as e:
            last_err = e
            continue
    raise last_err if last_err else RuntimeError(f"Failed to resolve service {name} for any known version")

def search_stream(client: GoogleAdsClient, customer_id: str, query: str) -> Tuple[List[Any], Optional[str]]:
    """
    Stream GAQL results into a list. Returns (rows, request_id).
    Uses the detected API version, with graceful service fallback.
    """
    results: List[Any] = []
    req_id: Optional[str] = None

    ga, _ver = _get_service_any_version(client, "GoogleAdsService")
    stream = ga.search_stream(customer_id=customer_id, query=query)

    for batch in stream:
        if req_id is None:
            req_id = getattr(batch, "request_id", None)
        for row in batch.results:
            results.append(row)
    return results, req_id

def micros_to_currency(micros: Optional[int]) -> float:
    try:
        return round((micros or 0) / 1_000_000.0, 6)
    except Exception:
        return 0.0

# ------------------------------------------------------------
# YTD report helpers
# ------------------------------------------------------------
def _ytd_bounds(today: Optional[dt.date] = None) -> Tuple[str, str]:
    """Return ('YYYY-01-01', 'YYYY-MM-DD') for current year-to-date."""
    today = today or dt.date.today()
    start = dt.date(today.year, 1, 1)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")

def _gaql_for_ytd(
    breakdown: Literal["customer", "campaign"] = "customer",
    include_zero_impressions: bool = False,
) -> str:
    """
    Build GAQL for YTD. We filter by date via a placeholder {DATE_FILTER} that will be replaced.
    If include_zero_impressions is False, we filter out rows where metrics.impressions = 0.
    """
    metrics = """
      metrics.impressions,
      metrics.clicks,
      metrics.ctr,
      metrics.cost_micros,
      metrics.average_cpc,
      metrics.average_cpm,
      metrics.conversions,
      metrics.conversions_value
    """

    if breakdown == "campaign":
        select = f"""
        SELECT
          customer.id,
          customer.descriptive_name,
          campaign.id,
          campaign.name,
          {metrics}
        FROM campaign
        """
    else:
        select = f"""
        SELECT
          customer.id,
          customer.descriptive_name,
          {metrics}
        FROM customer
        """

    filters: List[str] = ["{DATE_FILTER}"]
    if not include_zero_impressions:
        filters.append("metrics.impressions > 0")

    where_clause = "WHERE " + " AND ".join(filters)
    return f"""{select}
{where_clause}"""

def _to_float(x: Any) -> float:
    try:
        return float(x) if x is not None else 0.0
    except Exception:
        return 0.0

def _to_int(x: Any) -> int:
    try:
        return int(x or 0)
    except Exception:
        return 0

# ------------------------------------------------------------
# Public YTD runner
# ------------------------------------------------------------
def run_ytd_report(
    customer_id: str,
    breakdown: Literal["customer", "campaign"] = "customer",
    include_zero_impressions: bool = False,
) -> Dict[str, Any]:
    """Execute a YTD report for the given customer_id."""
    start, end = _ytd_bounds()
    date_filter = f"segments.date BETWEEN '{start}' AND '{end}'"

    gaql = _gaql_for_ytd(breakdown=breakdown, include_zero_impressions=include_zero_impressions)
    gaql_final = gaql.replace("{DATE_FILTER}", date_filter)

    client = google_ads_client()

    try:
        raw_rows, request_id = search_stream(client, customer_id, gaql_final)
    except GoogleAdsException as ex:
        detail = {
            "message": str(ex),
            "request_id": getattr(ex, "request_id", None),
            "failure": [{"code": e.error_code.__class__.__name__, "message": e.message} for e in ex.failure.errors],
            "gaql": gaql_final,
        }
        return {
            "ok": False,
            "error": detail,
            "date_range": {"start": start, "end": end},
            "customer_id": customer_id,
            "breakdown": breakdown,
        }

    rows: List[Dict[str, Any]] = []
    for r in raw_rows:
        m = r.metrics
        row: Dict[str, Any] = {
            "customer_id": getattr(r.customer, "id", None),
            "customer_name": getattr(r.customer, "descriptive_name", None),
            "impressions": _to_int(getattr(m, "impressions", 0)),
            "clicks": _to_int(getattr(m, "clicks", 0)),
            "ctr": _to_float(getattr(m, "ctr", 0.0)),
            "cost_micros": _to_int(getattr(m, "cost_micros", 0)),
            "cost": micros_to_currency(getattr(m, "cost_micros", 0)),
            "average_cpc": _to_float(getattr(m, "average_cpc", 0.0)),
            "average_cpm": _to_float(getattr(m, "average_cpm", 0.0)),
            "conversions": _to_float(getattr(m, "conversions", 0.0)),
            "conversions_value": _to_float(getattr(m, "conversions_value", 0.0)),
        }
        if breakdown == "campaign":
            row.update(
                {
                    "campaign_id": getattr(r.campaign, "id", None),
                    "campaign_name": getattr(r.campaign, "name", None),
                }
            )
        rows.append(row)

    return {
        "ok": True,
        "api_version": _API_VERSION,
        "date_range": {"start": start, "end": end},
        "customer_id": customer_id,
        "breakdown": breakdown,
        "rows": rows,
        "row_count": len(rows),
        "request_id": request_id,
        "gaql": gaql_final,
        "note": "Aggregated over YTD (Jan 1 to today). Set breakdown=campaign for per-campaign rows.",
    }

__all__ = [
    "google_ads_client",
    "search_stream",
    "micros_to_currency",
    "run_ytd_report",
    "_API_VERSION",
    "_get_service_any_version",  # exported for routers that want per-service fallback
]
