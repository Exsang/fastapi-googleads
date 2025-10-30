from typing import List, Tuple, Any, Dict, Optional, Literal
import datetime as dt

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from ..settings import settings
from .oauth import _load_client_config, read_refresh_token

# -----------------------------
# Core client & shared helpers
# -----------------------------
def google_ads_client() -> GoogleAdsClient:
    if not DEV_TOKEN:
        raise RuntimeError("Missing GOOGLE_ADS_DEVELOPER_TOKEN.")
    refresh_token = read_refresh_token()
    if not refresh_token:
        raise RuntimeError("Missing refresh token. Run the OAuth flow at /auth/start first.")
    cfg = _load_client_config()
    config = {
        "developer_token": DEV_TOKEN,
        "login_customer_id": LOGIN_CID if LOGIN_CID else None,
        "client_id": cfg["web"]["client_id"],
        "client_secret": cfg["web"]["client_secret"],
        "refresh_token": refresh_token,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(config)


def search_stream(client: GoogleAdsClient, customer_id: str, query: str) -> Tuple[List[Any], str | None]:
    ga = client.get_service("GoogleAdsService")
    stream = ga.search_stream(customer_id=customer_id, query=query)
    results: List[Any] = []
    req_id = None
    for batch in stream:
        if req_id is None:
            req_id = getattr(batch, "request_id", None)
        for row in batch.results:
            results.append(row)
    return results, req_id


def micros_to_currency(micros: int) -> float:
    try:
        return round((micros or 0) / 1_000_000, 6)
    except Exception:
        return 0.0


# -----------------------------
# YTD report helpers
# -----------------------------
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


# -----------------------------
# Public YTD runner
# -----------------------------
def run_ytd_report(
    customer_id: str,
    breakdown: Literal["customer", "campaign"] = "customer",
    include_zero_impressions: bool = False,
) -> Dict[str, Any]:
    """
    Execute a YTD report for the given customer_id.

    Returns:
      {
        ok: bool,
        date_range: {start, end},
        customer_id: str,
        breakdown: "customer"|"campaign",
        rows: [...],
        row_count: int,
        request_id: str|None,
        gaql: str,
        note: str
      }
    """
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
        "date_range": {"start": start, "end": end},
        "customer_id": customer_id,
        "breakdown": breakdown,
        "rows": rows,
        "row_count": len(rows),
        "request_id": request_id,
        "gaql": gaql_final,
        "note": "Aggregated over YTD (Jan 1 to today). Set breakdown=campaign for per-campaign rows.",
    }
