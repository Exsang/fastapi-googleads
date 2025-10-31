# app/services/google_ads.py
from __future__ import annotations

import os
from typing import Iterable, Tuple, List, Dict, Any

from google.ads.googleads.client import GoogleAdsClient


# ------------------------------------------------------------------------------
# Config / Client
# ------------------------------------------------------------------------------

def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def _google_ads_config_from_env() -> dict:
    """
    Build a google-ads config dict from environment variables only.
    Works cleanly with GitHub Codespaces secrets.
    """
    cfg = {
        "developer_token": _require_env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": _require_env("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": _require_env("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": _require_env("GOOGLE_ADS_REFRESH_TOKEN"),
        "login_customer_id": os.getenv("LOGIN_CUSTOMER_ID"),
        "use_proto_plus": True,
    }
    lcid = cfg.get("login_customer_id")
    if lcid:
        cfg["login_customer_id"] = str(lcid).replace("-", "")
    return cfg


def google_ads_client() -> GoogleAdsClient:
    """
    Return a configured GoogleAdsClient using only env vars.
    Avoids google-ads.yaml and any local secret files.
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
    stream = ga.search_stream(customer_id=str(customer_id).replace("-", ""), query=query)
    request_id = getattr(stream, "request_id", None)

    def _rows():
        for batch in stream:
            for row in batch.results:
                yield row

    return _rows(), request_id


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
    """
    Returns {"ok": bool, "request_id": str|None, "rows": [...], "breakdown": "..."}.
    """
    try:
        client = google_ads_client()
        where_zero = "" if include_zero_impressions else "AND metrics.impressions > 0"

        if breakdown == "campaign":
            query = f"""
              SELECT
                campaign.id, campaign.name, campaign.status,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
              FROM campaign
              WHERE segments.date DURING YEAR_TO_DATE
              {where_zero}
            """
        else:
            # default: customer-level
            query = f"""
              SELECT
                customer.id,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.conversions_value
              FROM customer
              WHERE segments.date DURING YEAR_TO_DATE
              {where_zero}
            """

        rows_iter, request_id = search_stream(client, customer_id, query)

        out: List[Dict[str, Any]] = []
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

        return {
            "ok": True,
            "request_id": request_id,
            "breakdown": breakdown,
            "rows": out,
        }

    except Exception as e:
        return {"ok": False, "error": str(e), "breakdown": breakdown}
