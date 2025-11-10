# app/routers/ytd.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from app.deps.auth import require_api_key
from typing import Optional, Literal, List
import csv
import io

from app.services.google_ads_reports import fetch_ytd_daily_from_google_ads
from app.services.ytd_repo import upsert_rows, fetch_rows_from_db

router = APIRouter(tags=["ads-ytd"])


@router.get("/ads/report-ytd-daily", dependencies=[Depends(require_api_key)])
def report_ytd_daily(
    customer_id: str = Query(...,
                             description="Google Ads customer ID (without dashes)"),
    refresh: bool = Query(
        False, description="If true, fetch from Google Ads and persist to DB before returning"),
    campaign_id: Optional[str] = Query(
        None, description="Optional filter for a single campaign"),
    format: Literal["json", "csv"] = Query("json", description="Output format")
):
    """
    YTD daily data repository endpoint.
    - refresh=true: pulls from Google Ads API and upserts into DB
    - format=csv: returns CSV text for analysis
    - otherwise reads from DB and returns JSON
    """
    if refresh:
        try:
            rows = fetch_ytd_daily_from_google_ads(customer_id=customer_id)
            upsert_rows(rows)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Google Ads fetch failed: {e}")

    data = fetch_rows_from_db(customer_id=customer_id, campaign_id=campaign_id)

    if format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=[
                "day", "customer_id", "campaign_id", "impressions", "clicks",
                "cost_micros", "conversions", "conversion_value"
            ]
        )
        writer.writeheader()
        for r in data:
            writer.writerow(r)
        return Response(content=buf.getvalue(), media_type="text/csv")

    return {"customer_id": customer_id, "count": len(data), "rows": data}
