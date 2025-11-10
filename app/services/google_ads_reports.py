# app/services/google_ads_reports.py
from __future__ import annotations
from datetime import date
from typing import Dict, Any, Iterable, List

from app.settings import SETTINGS
# assumes your existing helper
from app.services.google_ads import create_google_ads_client as get_google_ads_client


def _current_year_bounds() -> tuple[str, str]:
    today = date.today()
    start = date(today.year, 1, 1)
    return (start.isoformat(), today.isoformat())


def fetch_ytd_daily_from_google_ads(customer_id: str) -> List[Dict[str, Any]]:
    """
    Returns list of dict rows for YTD (Jan 1 → today), daily, by campaign.
    Requires your existing Google Ads client helper.
    """
    start, end = _current_year_bounds()
    # your existing wrapper should read tokens from env/SETTINGS
    client = get_google_ads_client()

    ga_service = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
          segments.date,
          customer.id,
          campaign.id,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY segments.date ASC
    """

    response = ga_service.search(customer_id=customer_id, query=query)

    out: List[Dict[str, Any]] = []
    for row in response:
        day = row.segments.date  # yyyy-mm-dd
        cid = row.customer.id
        camp = row.campaign.id if row.campaign else None
        m = row.metrics
        out.append({
            "day": date.fromisoformat(day),
            "customer_id": str(cid),
            "campaign_id": str(camp) if camp else None,
            "impressions": int(m.impressions),
            "clicks": int(m.clicks),
            "cost_micros": int(m.cost_micros),
            "conversions": float(m.conversions),
            "conversion_value": float(m.conversions_value),
        })
    return out
