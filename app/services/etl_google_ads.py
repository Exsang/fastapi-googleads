# app/services/etl_google_ads.py
from __future__ import annotations
from datetime import date
from typing import List, Dict, Any
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .google_ads import google_ads_client, search_stream
from .usage_log import record_quota_event
from ..db.models import (
    AdsDailyPerf,
    AdsCustomer,
    AdsCampaign,
    AdsAdGroup,
    AdsAd,
    AdsKeyword,
)

# Minimal campaign-level GAQL for a single day
_CAMPAIGN_DAILY_GAQL = """
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  customer.id,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.interactions,
  metrics.interaction_rate,
  metrics.ctr,
  metrics.engagements,
  metrics.engagement_rate,
  metrics.average_cpc,
  metrics.average_cpm,
  metrics.all_conversions,
  metrics.all_conversions_value
FROM campaign
WHERE segments.date = '{the_date}'
"""

_AD_GROUP_DAILY_GAQL = """
SELECT
    campaign.id,
    campaign.name,
    customer.id,
    ad_group.id,
    ad_group.name,
    ad_group.status,
    metrics.impressions,
    metrics.clicks,
    metrics.cost_micros,
    metrics.conversions,
    metrics.conversions_value,
    metrics.interactions,
    metrics.interaction_rate,
    metrics.ctr,
    metrics.engagements,
    metrics.engagement_rate,
    metrics.average_cpc,
    metrics.average_cpm,
    metrics.all_conversions,
    metrics.all_conversions_value
FROM ad_group
WHERE segments.date = '{the_date}'
"""

_AD_DAILY_GAQL = """
SELECT
    campaign.id,
    customer.id,
    ad_group.id,
    ad_group_ad.ad.id,
    ad_group_ad.status,
    ad_group_ad.ad.type,
    metrics.impressions,
    metrics.clicks,
    metrics.cost_micros,
    metrics.conversions,
    metrics.conversions_value,
    metrics.interactions,
    metrics.interaction_rate,
    metrics.ctr,
    metrics.average_cpc,
    metrics.average_cpm,
    metrics.engagements,
    metrics.engagement_rate,
    metrics.all_conversions,
    metrics.all_conversions_value
FROM ad_group_ad
WHERE segments.date = '{the_date}'
"""

_KEYWORD_DAILY_GAQL = """
SELECT
    campaign.id,
    customer.id,
    ad_group.id,
    ad_group_criterion.criterion_id,
    ad_group_criterion.status,
    ad_group_criterion.keyword.text,
    ad_group_criterion.keyword.match_type,
    metrics.impressions,
    metrics.clicks,
    metrics.cost_micros,
    metrics.conversions,
    metrics.conversions_value,
    metrics.interactions,
    metrics.interaction_rate,
    metrics.ctr,
    metrics.average_cpc,
    metrics.average_cpm,
    metrics.engagements,
    metrics.engagement_rate,
    metrics.all_conversions,
    metrics.all_conversions_value
FROM ad_group_criterion
WHERE segments.date = '{the_date}'
    AND ad_group_criterion.type = KEYWORD
"""


def fetch_campaign_day(customer_id: str, the_date: date) -> List[Dict[str, Any]]:
    client = google_ads_client()
    q = _CAMPAIGN_DAILY_GAQL.format(the_date=the_date.isoformat())
    rows_iter, req_id = search_stream(client, customer_id, q)
    try:
        record_quota_event("google_ads", "requests", 1, scope_id=customer_id,
                           request_id=req_id, endpoint="etl:campaign_day")
    except Exception:
        pass
    out = []
    for r in rows_iter:
        out.append({
            "perf_date": the_date,
            "level": "campaign",
            "customer_id": r.customer.id,
            "campaign_id": r.campaign.id,
            "ad_group_id": None,
            "ad_id": None,
            "criterion_id": None,
            "impressions": getattr(r.metrics, "impressions", 0),
            "clicks": getattr(r.metrics, "clicks", 0),
            "cost_micros": getattr(r.metrics, "cost_micros", 0),
            "conversions": getattr(r.metrics, "conversions", 0.0),
            "conversions_value": getattr(r.metrics, "conversions_value", 0.0),
            "interactions": getattr(r.metrics, "interactions", 0),
            "interaction_rate": getattr(r.metrics, "interaction_rate", 0.0),
            "ctr": getattr(r.metrics, "ctr", 0.0),
            "average_cpc_micros": int(getattr(r.metrics, "average_cpc", 0) * 1_000_000) if hasattr(r.metrics, "average_cpc") else None,
            "average_cpm_micros": int(getattr(r.metrics, "average_cpm", 0) * 1_000_000) if hasattr(r.metrics, "average_cpm") else None,
            "engagements": getattr(r.metrics, "engagements", 0),
            "engagement_rate": getattr(r.metrics, "engagement_rate", 0.0),
            "video_views": None,
            "video_view_rate": None,
            "all_conversions": getattr(r.metrics, "all_conversions", 0.0),
            "all_conversions_value": getattr(r.metrics, "all_conversions_value", 0.0),
            "metrics_json": {"raw": {"impressions": getattr(r.metrics, "impressions", 0)}},
            "request_id": req_id,
        })
    return out


def fetch_ad_group_day(customer_id: str, the_date: date) -> List[Dict[str, Any]]:
    client = google_ads_client()
    q = _AD_GROUP_DAILY_GAQL.format(the_date=the_date.isoformat())
    rows_iter, req_id = search_stream(client, customer_id, q)
    try:
        record_quota_event("google_ads", "requests", 1, scope_id=customer_id,
                           request_id=req_id, endpoint="etl:ad_group_day")
    except Exception:
        pass
    out = []
    for r in rows_iter:
        out.append({
            "perf_date": the_date,
            "level": "ad_group",
            "customer_id": r.customer.id,
            "campaign_id": r.campaign.id,
            "ad_group_id": r.ad_group.id,
            "ad_id": None,
            "criterion_id": None,
            "impressions": getattr(r.metrics, "impressions", 0),
            "clicks": getattr(r.metrics, "clicks", 0),
            "cost_micros": getattr(r.metrics, "cost_micros", 0),
            "conversions": getattr(r.metrics, "conversions", 0.0),
            "conversions_value": getattr(r.metrics, "conversions_value", 0.0),
            "interactions": getattr(r.metrics, "interactions", 0),
            "interaction_rate": getattr(r.metrics, "interaction_rate", 0.0),
            "ctr": getattr(r.metrics, "ctr", 0.0),
            "average_cpc_micros": int(getattr(r.metrics, "average_cpc", 0) * 1_000_000) if hasattr(r.metrics, "average_cpc") else None,
            "average_cpm_micros": int(getattr(r.metrics, "average_cpm", 0) * 1_000_000) if hasattr(r.metrics, "average_cpm") else None,
            "engagements": getattr(r.metrics, "engagements", 0),
            "engagement_rate": getattr(r.metrics, "engagement_rate", 0.0),
            "video_views": None,
            "video_view_rate": None,
            "all_conversions": getattr(r.metrics, "all_conversions", 0.0),
            "all_conversions_value": getattr(r.metrics, "all_conversions_value", 0.0),
            "metrics_json": {"raw": {"impressions": getattr(r.metrics, "impressions", 0)}},
            "request_id": req_id,
        })
    return out


def fetch_ad_day(customer_id: str, the_date: date) -> List[Dict[str, Any]]:
    client = google_ads_client()
    q = _AD_DAILY_GAQL.format(the_date=the_date.isoformat())
    rows_iter, req_id = search_stream(client, customer_id, q)
    try:
        record_quota_event("google_ads", "requests", 1, scope_id=customer_id,
                           request_id=req_id, endpoint="etl:ad_day")
    except Exception:
        pass
    out = []
    for r in rows_iter:
        ad_obj = None
        try:
            ad_obj = getattr(getattr(r, "ad_group_ad", None), "ad", None)
        except Exception:
            ad_obj = None
        out.append({
            "perf_date": the_date,
            "level": "ad",
            "customer_id": r.customer.id,
            "campaign_id": r.campaign.id,
            "ad_group_id": r.ad_group.id,
            "ad_id": getattr(ad_obj, "id", None),
            "criterion_id": None,
            "impressions": getattr(r.metrics, "impressions", 0),
            "clicks": getattr(r.metrics, "clicks", 0),
            "cost_micros": getattr(r.metrics, "cost_micros", 0),
            "conversions": getattr(r.metrics, "conversions", 0.0),
            "conversions_value": getattr(r.metrics, "conversions_value", 0.0),
            "interactions": getattr(r.metrics, "interactions", 0),
            "interaction_rate": getattr(r.metrics, "interaction_rate", 0.0),
            "ctr": getattr(r.metrics, "ctr", 0.0),
            "average_cpc_micros": int(getattr(r.metrics, "average_cpc", 0) * 1_000_000) if hasattr(r.metrics, "average_cpc") else None,
            "average_cpm_micros": int(getattr(r.metrics, "average_cpm", 0) * 1_000_000) if hasattr(r.metrics, "average_cpm") else None,
            "engagements": getattr(r.metrics, "engagements", 0),
            "engagement_rate": getattr(r.metrics, "engagement_rate", 0.0),
            "video_views": None,
            "video_view_rate": None,
            "all_conversions": getattr(r.metrics, "all_conversions", 0.0),
            "all_conversions_value": getattr(r.metrics, "all_conversions_value", 0.0),
            "metrics_json": {"raw": {"impressions": getattr(r.metrics, "impressions", 0)}},
            "request_id": req_id,
        })
    return out


def fetch_keyword_day(customer_id: str, the_date: date) -> List[Dict[str, Any]]:
    client = google_ads_client()
    q = _KEYWORD_DAILY_GAQL.format(the_date=the_date.isoformat())
    rows_iter, req_id = search_stream(client, customer_id, q)
    try:
        record_quota_event("google_ads", "requests", 1, scope_id=customer_id,
                           request_id=req_id, endpoint="etl:keyword_day")
    except Exception:
        pass
    out = []
    for r in rows_iter:
        kw = getattr(r, "ad_group_criterion", None)
        match_type = getattr(getattr(kw, "keyword", None), "match_type", None)
        out.append({
            "perf_date": the_date,
            "level": "keyword",
            "customer_id": r.customer.id,
            "campaign_id": r.campaign.id,
            "ad_group_id": r.ad_group.id,
            "ad_id": None,
            "criterion_id": kw.criterion_id if kw else None,
            "impressions": getattr(r.metrics, "impressions", 0),
            "clicks": getattr(r.metrics, "clicks", 0),
            "cost_micros": getattr(r.metrics, "cost_micros", 0),
            "conversions": getattr(r.metrics, "conversions", 0.0),
            "conversions_value": getattr(r.metrics, "conversions_value", 0.0),
            "interactions": getattr(r.metrics, "interactions", 0),
            "interaction_rate": getattr(r.metrics, "interaction_rate", 0.0),
            "ctr": getattr(r.metrics, "ctr", 0.0),
            "average_cpc_micros": int(getattr(r.metrics, "average_cpc", 0) * 1_000_000) if hasattr(r.metrics, "average_cpc") else None,
            "average_cpm_micros": int(getattr(r.metrics, "average_cpm", 0) * 1_000_000) if hasattr(r.metrics, "average_cpm") else None,
            "engagements": getattr(r.metrics, "engagements", 0),
            "engagement_rate": getattr(r.metrics, "engagement_rate", 0.0),
            "video_views": None,
            "video_view_rate": None,
            "all_conversions": getattr(r.metrics, "all_conversions", 0.0),
            "all_conversions_value": getattr(r.metrics, "all_conversions_value", 0.0),
            "metrics_json": {"raw": {"impressions": getattr(r.metrics, "impressions", 0)}},
            "request_id": req_id,
        })
    return out


# ---------------- Dimension Upserts -----------------

def _pg_upsert(model, rows: List[Dict[str, Any]], db: Session, pk_field: str, update_fields: List[str]) -> int:
    if not rows:
        return 0
    stmt = insert(model).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[getattr(model, pk_field)],
        set_={f: getattr(stmt.excluded, f) for f in update_fields},
    )
    r = db.execute(stmt)
    return r.rowcount or len(rows)


def upsert_customers(db: Session, rows: List[Dict[str, Any]]) -> int:
    # Expect keys: customer_id, descriptive_name?, currency_code?, time_zone?, manager?, status?
    return _pg_upsert(AdsCustomer, rows, db, "customer_id", [
        "descriptive_name", "currency_code", "time_zone", "manager", "status"
    ])


def upsert_campaigns(db: Session, rows: List[Dict[str, Any]]) -> int:
    return _pg_upsert(AdsCampaign, rows, db, "campaign_id", [
        "customer_id", "name", "status", "channel_type", "bidding_strategy_type"
    ])


def upsert_ad_groups(db: Session, rows: List[Dict[str, Any]]) -> int:
    return _pg_upsert(AdsAdGroup, rows, db, "ad_group_id", [
        "campaign_id", "name", "status", "type"
    ])


def upsert_ads(db: Session, rows: List[Dict[str, Any]]) -> int:
    return _pg_upsert(AdsAd, rows, db, "ad_id", [
        "ad_group_id", "type", "status", "final_urls", "headline"
    ])


def upsert_keywords(db: Session, rows: List[Dict[str, Any]]) -> int:
    return _pg_upsert(AdsKeyword, rows, db, "criterion_id", [
        "ad_group_id", "text", "match_type", "status"
    ])


def ensure_dimensions_for_campaign_rows(db: Session, perf_rows: List[Dict[str, Any]]) -> None:
    """Derive dimension row payloads from campaign-level perf rows and upsert.

    This keeps dimension tables current before fact insertion.
    """
    if not perf_rows:
        return
    # For now we only have campaign-level GAQL fields. Extend later for ad_group/ad/keyword.
    # Deduplicate by id.
    seen_campaign = set()
    campaign_dim_rows = []
    seen_customer = set()
    customer_dim_rows = []
    for r in perf_rows:
        cid = r["customer_id"]
        if cid not in seen_customer:
            seen_customer.add(cid)
            customer_dim_rows.append({"customer_id": cid})
        camp_id = r["campaign_id"]
        if camp_id and camp_id not in seen_campaign:
            seen_campaign.add(camp_id)
            campaign_dim_rows.append({
                "campaign_id": camp_id,
                "customer_id": cid,
                # name/status could be added by expanding GAQL later; placeholders kept minimal.
            })
    upsert_customers(db, customer_dim_rows)
    upsert_campaigns(db, campaign_dim_rows)


def ensure_dimensions_for_ad_group_rows(db: Session, perf_rows: List[Dict[str, Any]]) -> None:
    if not perf_rows:
        return
    seen_ag = set()
    ag_rows = []
    seen_campaign = set()
    campaign_rows = []
    for r in perf_rows:
        camp_id = r["campaign_id"]
        if camp_id and camp_id not in seen_campaign:
            seen_campaign.add(camp_id)
            campaign_rows.append(
                {"campaign_id": camp_id, "customer_id": r["customer_id"]})
        agid = r["ad_group_id"]
        if agid and agid not in seen_ag:
            seen_ag.add(agid)
            ag_rows.append({"ad_group_id": agid, "campaign_id": camp_id})
    upsert_campaigns(db, campaign_rows)
    upsert_ad_groups(db, ag_rows)


def ensure_dimensions_for_ad_rows(db: Session, perf_rows: List[Dict[str, Any]]) -> None:
    if not perf_rows:
        return
    seen_ad = set()
    ad_rows = []
    seen_ag = set()
    ag_rows = []
    for r in perf_rows:
        agid = r["ad_group_id"]
        if agid and agid not in seen_ag:
            seen_ag.add(agid)
            ag_rows.append(
                {"ad_group_id": agid, "campaign_id": r["campaign_id"]})
        adid = r.get("ad_id")
        if adid and adid not in seen_ad:
            seen_ad.add(adid)
            ad_rows.append({"ad_id": adid, "ad_group_id": agid})
    upsert_ad_groups(db, ag_rows)
    upsert_ads(db, ad_rows)


def ensure_dimensions_for_keyword_rows(db: Session, perf_rows: List[Dict[str, Any]]) -> None:
    if not perf_rows:
        return
    seen_kw = set()
    kw_rows = []
    seen_ag = set()
    ag_rows = []
    for r in perf_rows:
        agid = r["ad_group_id"]
        if agid and agid not in seen_ag:
            seen_ag.add(agid)
            ag_rows.append(
                {"ad_group_id": agid, "campaign_id": r["campaign_id"]})
        crit = r.get("criterion_id")
        if crit and crit not in seen_kw:
            seen_kw.add(crit)
            kw_rows.append({"criterion_id": crit, "ad_group_id": agid})
    upsert_ad_groups(db, ag_rows)
    upsert_keywords(db, kw_rows)


def upsert_daily_perf(rows: List[Dict[str, Any]], db: Session) -> int:
    if not rows:
        return 0
    # Normalize nullable key columns to empty strings because PK columns
    # are NOT NULL in Postgres even if SQLAlchemy declared nullable=True.
    # This keeps a stable composite key across levels.
    norm_rows: List[Dict[str, Any]] = []
    for r in rows:
        r2 = dict(r)
        for k in ("campaign_id", "ad_group_id", "ad_id", "criterion_id"):
            if r2.get(k) is None:
                r2[k] = ""
        norm_rows.append(r2)
    stmt = insert(AdsDailyPerf).values(norm_rows)
    pk_cols = [
        AdsDailyPerf.perf_date,
        AdsDailyPerf.level,
        AdsDailyPerf.customer_id,
        AdsDailyPerf.campaign_id,
        AdsDailyPerf.ad_group_id,
        AdsDailyPerf.ad_id,
        AdsDailyPerf.criterion_id,
    ]
    stmt = stmt.on_conflict_do_update(
        index_elements=pk_cols,
        set_={
            "impressions": stmt.excluded.impressions,
            "clicks": stmt.excluded.clicks,
            "cost_micros": stmt.excluded.cost_micros,
            "conversions": stmt.excluded.conversions,
            "conversions_value": stmt.excluded.conversions_value,
            "metrics_json": stmt.excluded.metrics_json,
            "request_id": stmt.excluded.request_id,
        },
    )
    result = db.execute(stmt)
    return result.rowcount or len(rows)


def ingest_campaign_day(db: Session, customer_id: str, the_date: date) -> Dict[str, Any]:
    rows = fetch_campaign_day(customer_id, the_date)
    # Upsert dimension tables first (idempotent)
    ensure_dimensions_for_campaign_rows(db, rows)
    count = upsert_daily_perf(rows, db)
    return {"ok": True, "rows": count, "date": the_date.isoformat(), "level": "campaign"}


FETCH_MAP = {
    "campaign": fetch_campaign_day,
    "ad_group": fetch_ad_group_day,
    "ad": fetch_ad_day,
    "keyword": fetch_keyword_day,
}

DIMENSION_ENSURE_MAP = {
    "campaign": ensure_dimensions_for_campaign_rows,
    "ad_group": ensure_dimensions_for_ad_group_rows,
    "ad": ensure_dimensions_for_ad_rows,
    "keyword": ensure_dimensions_for_keyword_rows,
}


def ingest_multi_level_day(db: Session, customer_id: str, the_date: date, levels: List[str] | None = None) -> Dict[str, Any]:
    levels = [l.strip().lower() for l in (
        levels or ["campaign", "ad_group", "ad", "keyword"]) if l.strip()]
    results = []
    total_rows = 0
    for lvl in levels:
        fetch_fn = FETCH_MAP.get(lvl)
        dim_fn = DIMENSION_ENSURE_MAP.get(lvl)
        if not fetch_fn or not dim_fn:
            results.append({"level": lvl, "ok": False,
                           "error": "Unsupported level"})
            continue
        rows = fetch_fn(customer_id, the_date)
        dim_fn(db, rows)
        count = upsert_daily_perf(rows, db)
        results.append({"level": lvl, "rows": count, "ok": True})
        total_rows += count
    return {"ok": True, "date": the_date.isoformat(), "levels": levels, "results": results, "total_rows": total_rows}
