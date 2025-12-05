# app/services/google_ads.py
from __future__ import annotations

import os
from typing import Iterable, Tuple, List, Dict, Any
import time
import logging
try:
    import grpc  # type: ignore
except Exception:  # pragma: no cover
    grpc = None  # fallback if not available; we'll do best-effort retries

from google.ads.googleads.client import GoogleAdsClient


# ------------------------------------------------------------------------------
# Config / Client
# ------------------------------------------------------------------------------

def _require_env(name: str) -> str:
    """Return required env var or raise RuntimeError (caught upstream)."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def _google_ads_config_from_env() -> dict:
    """Build google-ads config from env vars only, returning dict.

    This function raises RuntimeError if any required variable is missing.
    """
    cfg = {
        "developer_token": _require_env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": _require_env("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": _require_env("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": _require_env("GOOGLE_ADS_REFRESH_TOKEN"),
        "login_customer_id": os.getenv("LOGIN_CUSTOMER_ID"),  # optional
        "use_proto_plus": True,
    }
    lcid = cfg.get("login_customer_id")
    if lcid:
        cfg["login_customer_id"] = str(lcid).replace("-", "")
    return cfg


def ensure_google_ads_env() -> dict:
    """Return a dict with keys: ok (bool), missing (list[str]).

    Does not raise; purely reports missing required env variables so endpoints can
    surface a clean client error (400) vs ambiguous runtime exceptions.
    """
    required = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
    ]
    missing = [name for name in required if not os.getenv(name)]
    return {"ok": len(missing) == 0, "missing": missing}


def google_ads_client() -> GoogleAdsClient:
    """Return configured GoogleAdsClient using only env vars.

    Raises RuntimeError if required env vars are missing (caught by callers that
    choose to convert to structured error responses).
    """
    return GoogleAdsClient.load_from_dict(_google_ads_config_from_env())


# Keep for payloads/logging only (do NOT use to pin client calls).
_API_VERSION: str = os.getenv("GOOGLE_ADS_API_VERSION", "auto")


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def search_stream(
    client: GoogleAdsClient,
    customer_id: str,
    query: str,
) -> Tuple[Iterable, str | None]:
    """
    Stream GAQL results. Returns (rows_iterable, request_id_or_None).
    """
    ga = client.get_service("GoogleAdsService")
    stream = ga.search_stream(customer_id=str(
        customer_id).replace("-", ""), query=query)
    request_id = getattr(stream, "request_id", None)

    def _rows():
        for batch in stream:
            for row in batch.results:
                yield row

    return _rows(), request_id


# ------------------------------------------------------------------------------
# Resilient wrapper with retries/backoff for transient gRPC failures
# ------------------------------------------------------------------------------

_RETRYABLE_STATUS = {
    # Network or transient server states
    getattr(getattr(grpc, "StatusCode", object), "UNAVAILABLE", None),
    getattr(getattr(grpc, "StatusCode", object), "DEADLINE_EXCEEDED", None),
    getattr(getattr(grpc, "StatusCode", object), "CANCELLED", None),
    getattr(getattr(grpc, "StatusCode", object), "INTERNAL", None),
}


def search_stream_resilient(
    customer_id: str,
    query: str,
    attempts: int = 4,
    initial_backoff: float = 1.0,
) -> Tuple[Iterable, str | None]:
    """Attempt search_stream with retries on transient gRPC errors.

    Rebuilds the Google Ads client on each retry to refresh the channel.
    Non-retryable errors (e.g., INVALID_ARGUMENT / UNRECOGNIZED_FIELD) are raised immediately.
    """
    logger = logging.getLogger("google_ads_resilient")
    last_exc: Exception | None = None
    backoff = initial_backoff
    for attempt in range(1, max(1, attempts) + 1):
        try:
            client = google_ads_client()
            return search_stream(client, customer_id, query)
        except Exception as e:  # try to detect retryable gRPC
            last_exc = e
            if grpc is not None and isinstance(e, grpc.RpcError):
                code = e.code()
                if code in _RETRYABLE_STATUS:
                    logger.warning(
                        "search_stream retryable error %s on attempt %d/%d; backing off %.1fs",
                        code,
                        attempt,
                        attempts,
                        backoff,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
            # Not retryable or grpc not present; raise
            raise
    # Exhausted
    assert last_exc is not None
    raise last_exc


def micros_to_currency(micros: int | float | None) -> float:
    try:
        return round(float(micros or 0) / 1_000_000.0, 6)
    except Exception:
        return 0.0


# ------------------------------------------------------------------------------
# Example YTD report (used by /ads/report-ytd)
# ------------------------------------------------------------------------------

def run_ytd_report(
    customer_id: str,
    breakdown: str = "customer",
    include_zero_impressions: bool = False,
) -> Dict[str, Any]:
    """Compute year-to-date metrics for customer or campaign breakdown.

    NOTE: GAQL macro YEAR_TO_DATE is not valid; use THIS_YEAR.

    Returns a structured dict:
      {"ok": bool, "request_id": str|None, "rows": [...], "breakdown": str, "error"?: str, "missing"?: [..]}
    """
    env_check = ensure_google_ads_env()
    if not env_check["ok"]:
        return {
            "ok": False,
            "error": f"Missing Google Ads env variables: {', '.join(env_check['missing'])}",
            "missing": env_check["missing"],
            "breakdown": breakdown,
        }

    try:
        client = google_ads_client()
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "breakdown": breakdown}
    except Exception as e:
        return {"ok": False, "error": f"Client init failed: {e}", "breakdown": breakdown}

    where_zero = "" if include_zero_impressions else "AND metrics.impressions > 0"

    if breakdown == "campaign":
        query = f"""
          SELECT
            campaign.id, campaign.name, campaign.status,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.conversions_value
          FROM campaign
          WHERE segments.date DURING THIS_YEAR
          {where_zero}
        """
    else:
        query = f"""
          SELECT
            customer.id,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.conversions_value
          FROM customer
          WHERE segments.date DURING THIS_YEAR
          {where_zero}
        """

    try:
        rows_iter, request_id = search_stream(client, customer_id, query)
    except Exception as e:
        return {"ok": False, "error": f"Query failed: {e}", "breakdown": breakdown}

    out: List[Dict[str, Any]] = []
    try:
        for r in rows_iter:
            if breakdown == "campaign":
                out.append({
                    "campaign_id": r.campaign.id,
                    "name": r.campaign.name,
                    "status": getattr(r.campaign.status, "name", str(r.campaign.status)),
                    "impressions": getattr(r.metrics, "impressions", 0),
                    "clicks": getattr(r.metrics, "clicks", 0),
                    "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                    "conversions": getattr(r.metrics, "conversions", 0.0),
                    "conv_value": getattr(r.metrics, "conversions_value", 0.0),
                })
            else:
                out.append({
                    "customer_id": r.customer.id,
                    "impressions": getattr(r.metrics, "impressions", 0),
                    "clicks": getattr(r.metrics, "clicks", 0),
                    "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                    "conversions": getattr(r.metrics, "conversions", 0.0),
                    "conv_value": getattr(r.metrics, "conversions_value", 0.0),
                })
    except Exception as e:
        return {"ok": False, "error": f"Row parse failed: {e}", "breakdown": breakdown}

    return {
        "ok": True,
        "request_id": request_id,
        "breakdown": breakdown,
        "rows": out,
    }


# ------------------------------------------------------------------------------
# Year-to-date DAILY campaign report (consolidated from legacy google_ads_reports.py)
# ------------------------------------------------------------------------------

def run_ytd_daily_campaign_report(
    customer_id: str,
    include_zero_impressions: bool = False,
    source: str = "live",  # 'live' | 'db' | 'auto'
    db: Any | None = None,
) -> Dict[str, Any]:
    """Return YTD daily metrics at the campaign level.

    Shape:
      {"ok": bool, "request_id": str|None, "rows": [ {"day": yyyy-mm-dd, "campaign_id": str,
         "name": str, "status": str, impressions, clicks, cost, conversions, conv_value} ], "error"?: str}

    This consolidates former functionality from:
      - app/services/google_ads_reports.py (fetch_ytd_daily_from_google_ads)
      - app/services/ytd_repo.py (ad-hoc persistence layer)

    We intentionally do NOT persist these rows separately now; callers can export CSV directly.
    Persistence should happen via the unified ETL pipeline instead of a bespoke ytd_daily table.
    """
    # DB-backed path: when source in {"db","auto"} and db provided, attempt assemble from AdsDailyPerf
    if source in {"db", "auto"} and db is not None:
        try:
            from sqlalchemy import select
            from datetime import date
            from app.db.models import AdsDailyPerf, AdsCampaign
            today = date.today()
            start = date(today.year, 1, 1)
            stmt = (
                select(AdsDailyPerf, AdsCampaign)
                .where(AdsDailyPerf.customer_id == customer_id)
                .where(AdsDailyPerf.level == "campaign")
                .where(AdsDailyPerf.perf_date >= start)
                .where(AdsDailyPerf.perf_date <= today)
                .join(AdsCampaign, AdsCampaign.campaign_id == AdsDailyPerf.campaign_id, isouter=True)
                .order_by(AdsDailyPerf.perf_date.asc(), AdsDailyPerf.campaign_id.asc())
            )
            rows = db.execute(stmt).all()
            out_rows: List[Dict[str, Any]] = []
            for perf, camp in rows:
                # Filter zero impressions if requested
                if not include_zero_impressions and (perf.impressions or 0) <= 0:
                    continue
                out_rows.append({
                    "day": perf.perf_date.isoformat(),
                    "campaign_id": perf.campaign_id or None,
                    "name": getattr(camp, "name", None),
                    "status": getattr(camp, "status", None),
                    "impressions": perf.impressions,
                    "clicks": perf.clicks,
                    "cost": micros_to_currency(perf.cost_micros or 0),
                    "conversions": perf.conversions,
                    "conv_value": perf.conversions_value,
                })
            # If source=='db' we return directly, even if empty
            if source == "db" or (source == "auto" and out_rows):
                return {
                    "ok": True,
                    "request_id": None,
                    "rows": out_rows,
                    "period": "THIS_YEAR",
                    "granularity": "daily",
                    "source": "db",
                }
        except Exception as _db_err:
            if source == "db":
                return {"ok": False, "error": f"DB path failed: {_db_err}"}
            # fall through to live path for 'auto'

    # Live path (fetch directly)
    env_check = ensure_google_ads_env()
    if not env_check["ok"]:
        return {
            "ok": False,
            "error": f"Missing Google Ads env variables: {', '.join(env_check['missing'])}",
            "missing": env_check["missing"],
        }

    try:
        client = google_ads_client()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Client init failed: {e}"}

    where_zero = "" if include_zero_impressions else "AND metrics.impressions > 0"

    query = f"""
        SELECT
          segments.date,
          campaign.id,
          campaign.name,
          campaign.status,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING THIS_YEAR
        {where_zero}
        ORDER BY segments.date ASC
    """

    try:
        rows_iter, request_id = search_stream(client, customer_id, query)
    except Exception as e:
        return {"ok": False, "error": f"Query failed: {e}"}

    out: List[Dict[str, Any]] = []
    try:
        for r in rows_iter:
            day_val = getattr(r.segments, "date", None)
            out.append({
                "day": day_val,
                "campaign_id": getattr(r.campaign, "id", None),
                "name": getattr(r.campaign, "name", None),
                "status": getattr(getattr(r.campaign, "status", ""), "name", str(getattr(r.campaign, "status", ""))),
                "impressions": getattr(r.metrics, "impressions", 0),
                "clicks": getattr(r.metrics, "clicks", 0),
                "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                "conversions": getattr(r.metrics, "conversions", 0.0),
                "conv_value": getattr(r.metrics, "conversions_value", 0.0),
            })
    except Exception as e:
        return {"ok": False, "error": f"Row parse failed: {e}"}

    return {
        "ok": True,
        "request_id": request_id,
        "rows": out,
        "period": "THIS_YEAR",
        "granularity": "daily",
        "source": "live",
    }


def run_mtd_campaign_report(
    customer_id: str,
    include_zero_impressions: bool = False,
) -> Dict[str, Any]:
    """Return month-to-date metrics at the campaign level.

    Uses GAQL macro THIS_MONTH for the current calendar month.

    Response shape:
      {"ok": bool, "request_id": str|None, "rows": [ {campaign_id, name, status, impressions, clicks, cost, conversions, conv_value} ], "missing"?: [...], "error"?: str}
    """
    env_check = ensure_google_ads_env()
    if not env_check["ok"]:
        return {
            "ok": False,
            "error": f"Missing Google Ads env variables: {', '.join(env_check['missing'])}",
            "missing": env_check["missing"],
        }

    try:
        client = google_ads_client()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Client init failed: {e}"}

    where_zero = "" if include_zero_impressions else "AND metrics.impressions > 0"
    query = f"""
      SELECT
        campaign.id, campaign.name, campaign.status,
        metrics.impressions, metrics.clicks, metrics.cost_micros,
        metrics.conversions, metrics.conversions_value
      FROM campaign
      WHERE segments.date DURING THIS_MONTH
      {where_zero}
    """

    try:
        rows_iter, request_id = search_stream(client, customer_id, query)
    except Exception as e:
        return {"ok": False, "error": f"Query failed: {e}"}

    out: List[Dict[str, Any]] = []
    try:
        for r in rows_iter:
            out.append({
                "campaign_id": r.campaign.id,
                "name": r.campaign.name,
                "status": getattr(r.campaign.status, "name", str(r.campaign.status)),
                "impressions": getattr(r.metrics, "impressions", 0),
                "clicks": getattr(r.metrics, "clicks", 0),
                "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                "conversions": getattr(r.metrics, "conversions", 0.0),
                "conv_value": getattr(r.metrics, "conversions_value", 0.0),
            })
    except Exception as e:
        return {"ok": False, "error": f"Row parse failed: {e}"}

    return {
        "ok": True,
        "request_id": request_id,
        "rows": out,
        "period": "THIS_MONTH",
    }


def run_mtd_level_report(
    customer_id: str,
    level: str = "campaign",
    include_zero_impressions: bool = False,
) -> Dict[str, Any]:
    """Month-to-date metrics for various entity levels.

    level: one of {"campaign", "ad_group", "ad", "keyword"}
    """
    env_check = ensure_google_ads_env()
    if not env_check["ok"]:
        return {
            "ok": False,
            "error": f"Missing Google Ads env variables: {', '.join(env_check['missing'])}",
            "missing": env_check["missing"],
        }

    try:
        client = google_ads_client()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Client init failed: {e}"}

    where_zero = "" if include_zero_impressions else "AND metrics.impressions > 0"

    level = (level or "campaign").lower()
    if level == "campaign":
        query = f"""
          SELECT
            campaign.id, campaign.name, campaign.status,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.conversions_value
          FROM campaign
          WHERE segments.date DURING THIS_MONTH
          {where_zero}
        """
    elif level == "ad_group":
        query = f"""
          SELECT
            ad_group.id, ad_group.name, ad_group.status,
            campaign.id, campaign.name,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.conversions_value
          FROM ad_group
          WHERE segments.date DURING THIS_MONTH
          {where_zero}
        """
    elif level == "ad":
        query = f"""
          SELECT
            ad_group_ad.ad.id,
            ad_group_ad.status,
            ad_group_ad.ad.type,
            ad_group.id, ad_group.name,
            campaign.id, campaign.name,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.conversions_value
          FROM ad_group_ad
          WHERE segments.date DURING THIS_MONTH
          {where_zero}
        """
    elif level == "keyword":
        query = f"""
          SELECT
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.status,
            ad_group.id, ad_group.name,
            campaign.id, campaign.name,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.conversions_value
          FROM ad_group_criterion
          WHERE segments.date DURING THIS_MONTH
            AND ad_group_criterion.type = KEYWORD
          {where_zero}
        """
    else:
        return {"ok": False, "error": f"Unsupported level: {level}"}

    try:
        rows_iter, request_id = search_stream(client, customer_id, query)
    except Exception as e:
        return {"ok": False, "error": f"Query failed: {e}"}

    out: List[Dict[str, Any]] = []
    try:
        for r in rows_iter:
            if level == "campaign":
                out.append({
                    "campaign_id": r.campaign.id,
                    "name": r.campaign.name,
                    "status": getattr(r.campaign.status, "name", str(r.campaign.status)),
                    "impressions": getattr(r.metrics, "impressions", 0),
                    "clicks": getattr(r.metrics, "clicks", 0),
                    "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                    "conversions": getattr(r.metrics, "conversions", 0.0),
                    "conv_value": getattr(r.metrics, "conversions_value", 0.0),
                })
            elif level == "ad_group":
                out.append({
                    "ad_group_id": r.ad_group.id,
                    "ad_group_name": r.ad_group.name,
                    "status": getattr(r.ad_group.status, "name", str(r.ad_group.status)),
                    "campaign_id": r.campaign.id,
                    "campaign_name": r.campaign.name,
                    "impressions": getattr(r.metrics, "impressions", 0),
                    "clicks": getattr(r.metrics, "clicks", 0),
                    "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                    "conversions": getattr(r.metrics, "conversions", 0.0),
                    "conv_value": getattr(r.metrics, "conversions_value", 0.0),
                })
            elif level == "ad":
                out.append({
                    "ad_id": r.ad_group_ad.ad.id,
                    "ad_type": getattr(r.ad_group_ad.ad.type, "name", str(r.ad_group_ad.ad.type)) if getattr(r.ad_group_ad, "ad", None) else None,
                    "status": getattr(getattr(r.ad_group_ad, "status", None), "name", str(getattr(r.ad_group_ad, "status", ""))),
                    "ad_group_id": r.ad_group.id,
                    "ad_group_name": r.ad_group.name,
                    "campaign_id": r.campaign.id,
                    "campaign_name": r.campaign.name,
                    "impressions": getattr(r.metrics, "impressions", 0),
                    "clicks": getattr(r.metrics, "clicks", 0),
                    "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                    "conversions": getattr(r.metrics, "conversions", 0.0),
                    "conv_value": getattr(r.metrics, "conversions_value", 0.0),
                })
            elif level == "keyword":
                mt = getattr(getattr(r.ad_group_criterion,
                             "keyword", None), "match_type", None)
                out.append({
                    "text": getattr(getattr(r.ad_group_criterion, "keyword", None), "text", None),
                    "match_type": getattr(mt, "name", str(mt)) if mt is not None else None,
                    "status": getattr(r.ad_group_criterion.status, "name", str(r.ad_group_criterion.status)),
                    "ad_group_id": r.ad_group.id,
                    "ad_group_name": r.ad_group.name,
                    "campaign_id": r.campaign.id,
                    "campaign_name": r.campaign.name,
                    "impressions": getattr(r.metrics, "impressions", 0),
                    "clicks": getattr(r.metrics, "clicks", 0),
                    "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                    "conversions": getattr(r.metrics, "conversions", 0.0),
                    "conv_value": getattr(r.metrics, "conversions_value", 0.0),
                })
    except Exception as e:
        return {"ok": False, "error": f"Row parse failed: {e}"}

    return {"ok": True, "request_id": request_id, "rows": out, "level": level, "period": "THIS_MONTH"}


def run_search_terms_report(
    customer_id: str,
    days: int = 30,
    include_zero_impressions: bool = False,
) -> Dict[str, Any]:
    """Return recent search terms with aggregated metrics over the last N days.

    Response shape:
      {"ok": bool, "request_id": str|None, "rows": [ {search_term, campaign_id, ad_group_id, impressions, clicks, cost, conversions, conv_value} ], "period": "LAST_N_DAYS"}
    """
    env_check = ensure_google_ads_env()
    if not env_check["ok"]:
        return {
            "ok": False,
            "error": f"Missing Google Ads env variables: {', '.join(env_check['missing'])}",
            "missing": env_check["missing"],
        }

    try:
        client = google_ads_client()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Client init failed: {e}"}

    where_zero = "" if include_zero_impressions else "AND metrics.impressions > 0"
    d = max(1, int(days or 1))
    # GAQL macro for last N days
    query = f"""
      SELECT
        search_term_view.search_term,
        campaign.id,
        ad_group.id,
        metrics.impressions, metrics.clicks, metrics.cost_micros,
        metrics.conversions, metrics.conversions_value
      FROM search_term_view
      WHERE segments.date DURING LAST_{d}_DAYS
      {where_zero}
    """

    try:
        rows_iter, request_id = search_stream(client, customer_id, query)
    except Exception as e:
        return {"ok": False, "error": f"Query failed: {e}"}

    out: List[Dict[str, Any]] = []
    try:
        for r in rows_iter:
            term = getattr(getattr(r, "search_term_view", None),
                           "search_term", None)
            out.append({
                "search_term": term,
                "campaign_id": getattr(r.campaign, "id", None),
                "ad_group_id": getattr(r.ad_group, "id", None),
                "impressions": getattr(r.metrics, "impressions", 0),
                "clicks": getattr(r.metrics, "clicks", 0),
                "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
                "conversions": getattr(r.metrics, "conversions", 0.0),
                "conv_value": getattr(r.metrics, "conversions_value", 0.0),
            })
    except Exception as e:
        return {"ok": False, "error": f"Row parse failed: {e}"}

    return {"ok": True, "request_id": request_id, "rows": out, "period": f"LAST_{d}_DAYS"}


# Ensure stable public API names expected elsewhere
if "create_google_ads_client" not in globals():
    _candidates = (
        "get_google_ads_client",
        "create_client",
        "build_google_ads_client",
        "google_ads_client",
        "get_client",
    )
    for _n in _candidates:
        if _n in globals():
            globals()["create_google_ads_client"] = globals()[
                _n]  # type: ignore[assignment]
            break
    else:
        if "GoogleAdsClient" in globals():
            # type: ignore[no-redef]
            def create_google_ads_client(*args, **kwargs):
                return globals()["GoogleAdsClient"](*args, **kwargs)
            # type: ignore[assignment]
            globals()["create_google_ads_client"] = create_google_ads_client
        # else: leave undefined; callers should import google_ads_client

if "get_google_ads_client" not in globals() and "create_google_ads_client" in globals():
    globals()["get_google_ads_client"] = globals()[
        "create_google_ads_client"]  # type: ignore[assignment]
