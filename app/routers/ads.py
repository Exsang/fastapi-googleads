# app/routers/ads.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from typing import Literal
from google.ads.googleads.errors import GoogleAdsException

from ..deps.auth import require_auth
from ..settings import DEFAULT_MCC_ID
from ..services.google_ads import (
    google_ads_client,
    search_stream,
    micros_to_currency,
    run_ytd_report,
    _API_VERSION,  # kept for returning in payloads/logging only
)
from ..services.usage_log import log_api_usage

router = APIRouter(tags=["ads"], dependencies=[Depends(require_auth)])

# ---------------------------
# CUSTOMERS
# ---------------------------
@router.get("/customers")
def list_customers():
    try:
        client = google_ads_client()
        svc = client.get_service("CustomerService")
        resp = svc.list_accessible_customers()
        ids = [rn.split("/")[-1] for rn in resp.resource_names]
        log_api_usage(
            scope_id="global",
            request_id=getattr(resp, "request_id", None),
            endpoint="/ads/customers",
            request_type="list",
            operations=0,
        )
        return {"api_version": _API_VERSION, "customers": ids}
    except GoogleAdsException as e:
        errors = [
            {"code": err.error_code.WhichOneof("error_code"), "message": err.message}
            for err in e.failure.errors
        ]
        raise HTTPException(status_code=400, detail={"request_id": e.request_id, "errors": errors})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------
# EXAMPLE REPORT
# ---------------------------
@router.get("/example-report")
def example_report(customer_id: str):
    try:
        client = google_ads_client()
        ga = client.get_service("GoogleAdsService")
        query = """
            SELECT campaign.id, campaign.name, campaign.status
            FROM campaign
            ORDER BY campaign.id
            LIMIT 10
        """
        req = client.get_type("SearchGoogleAdsRequest")
        req.customer_id = customer_id
        req.query = query
        rows = ga.search(request=req)
        items = [{"id": r.campaign.id, "name": r.campaign.name, "status": r.campaign.status.name} for r in rows]
        log_api_usage(
            scope_id=customer_id,
            request_id=getattr(rows, "request_id", None),
            endpoint="/ads/example-report",
            request_type="search",
            operations=0,
        )
        return {"api_version": _API_VERSION, "campaigns": items}
    except GoogleAdsException as e:
        errors = [
            {"code": err.error_code.WhichOneof("error_code"), "message": err.message}
            for err in e.failure.errors
        ]
        raise HTTPException(status_code=400, detail={"request_id": e.request_id, "errors": errors})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------
# ACTIVE ACCOUNTS
# ---------------------------
@router.get("/active-accounts")
def list_active_accounts(mcc_id: str = DEFAULT_MCC_ID, include_submanagers: bool = False):
    try:
        client = google_ads_client()
        ga = client.get_service("GoogleAdsService")
        query = """
            SELECT
              customer_client.client_customer,
              customer_client.id,
              customer_client.descriptive_name,
              customer_client.currency_code,
              customer_client.time_zone,
              customer_client.level,
              customer_client.manager,
              customer_client.status,
              customer_client.hidden,
              customer_client.test_account
            FROM customer_client
            WHERE customer_client.level = 1
              AND customer_client.status = 'ENABLED'
              AND customer_client.hidden = FALSE
        """
        if not include_submanagers:
            query += "\n  AND customer_client.manager = FALSE"

        resp = ga.search(customer_id=mcc_id, query=query)
        items = []
        for r in resp:
            cc = r.customer_client
            cid = cc.client_customer.split("/")[-1] if cc.client_customer else str(cc.id)
            items.append({
                "customer_id": cid,
                "name": cc.descriptive_name,
                "currency": cc.currency_code,
                "time_zone": cc.time_zone,
                "is_manager": cc.manager,
                "status": cc.status.name if hasattr(cc.status, "name") else str(cc.status),
                "test_account": getattr(cc, "test_account", False),
                "level": cc.level,
            })

        log_api_usage(
            scope_id=mcc_id,
            request_id=getattr(resp, "request_id", None),
            endpoint="/ads/active-accounts",
            request_type="search",
            operations=0,
        )
        return {
            "api_version": _API_VERSION,
            "mcc_id": mcc_id,
            "count": len(items),
            "request_id": getattr(resp, "request_id", None),
            "accounts": items,
        }
    except GoogleAdsException as e:
        errors = [
            {"code": err.error_code.WhichOneof("error_code"), "message": err.message}
            for err in e.failure.errors
        ]
        raise HTTPException(status_code=400, detail={"request_id": e.request_id, "errors": errors})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------
# 30-DAY REPORT
# ---------------------------
@router.get("/report-30d")
def report_30d(customer_id: str):
    try:
        client = google_ads_client()

        # Uses search_stream(), which already handles versioning internally.
        q_campaigns = """
          SELECT
            campaign.id, campaign.name, campaign.status,
            campaign.advertising_channel_type, campaign.bidding_strategy_type,
            metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value
          FROM campaign
          WHERE segments.date DURING LAST_30_DAYS
        """
        rows, _ = search_stream(client, customer_id, q_campaigns)
        campaigns = [{
            "campaign_id": r.campaign.id,
            "name": r.campaign.name,
            "status": r.campaign.status.name if hasattr(r.campaign.status, "name") else str(r.campaign.status),
            "channel": r.campaign.advertising_channel_type.name if hasattr(r.campaign.advertising_channel_type, "name") else str(r.campaign.advertising_channel_type),
            "bid_strategy": r.campaign.bidding_strategy_type.name if hasattr(r.campaign.bidding_strategy_type, "name") else str(r.campaign.bidding_strategy_type),
            "impressions": getattr(r.metrics, "impressions", 0),
            "clicks": getattr(r.metrics, "clicks", 0),
            "cost": micros_to_currency(getattr(r.metrics, "cost_micros", 0)),
            "conversions": getattr(r.metrics, "conversions", 0.0),
            "conv_value": getattr(r.metrics, "conversions_value", 0.0),
        } for r in rows]

        return {"api_version": _API_VERSION, "customer_id": customer_id, "campaigns": campaigns}
    except GoogleAdsException as e:
        errors = [
            {"code": err.error_code.WhichOneof("error_code"), "message": err.message}
            for err in e.failure.errors
        ]
        raise HTTPException(status_code=400, detail={"request_id": e.request_id, "errors": errors})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------
# YEAR-TO-DATE REPORT
# ---------------------------
@router.get("/report-ytd")
def report_ytd(
    customer_id: str,
    breakdown: Literal["customer", "campaign"] = "customer",
    include_zero_impressions: bool = False,
):
    try:
        result = run_ytd_report(
            customer_id=customer_id,
            breakdown=breakdown,
            include_zero_impressions=include_zero_impressions,
        )
        if not result.get("ok", False):
            raise HTTPException(status_code=400, detail=result.get("error"))

        log_api_usage(
            scope_id=customer_id,
            request_id=result.get("request_id"),
            endpoint="/ads/report-ytd",
            request_type="search",
            operations=0,
        )
        # run_ytd_report already used the pinned version via search_stream()
        result.setdefault("api_version", _API_VERSION)
        return result
    except GoogleAdsException as e:
        errors = [
            {"code": err.error_code.WhichOneof("error_code"), "message": err.message}
            for err in e.failure.errors
        ]
        raise HTTPException(status_code=400, detail={"request_id": e.request_id, "errors": errors})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------
# KEYWORD IDEAS
# ---------------------------
@router.get("/keyword-ideas")
def keyword_ideas(
    customer_id: str,
    seed: str | None = None,
    url: str | None = None,
    geo: str = "2840",
    lang: int = 1000,
    network: str = "google",
    limit: int = 100,
):
    try:
        client = google_ads_client()
        lang_path = f"languageConstants/{int(lang)}"
        geo_ids = [g.strip() for g in geo.split(",") if g.strip()]
        geo_paths = [f"geoTargetConstants/{int(g)}" for g in geo_ids]
        kp_enum = client.enums.KeywordPlanNetworkEnum.KeywordPlanNetwork
        kp_network = kp_enum.GOOGLE_SEARCH if network.lower() == "google" else kp_enum.GOOGLE_SEARCH_AND_PARTNERS

        svc = client.get_service("KeywordPlanIdeaService")
        req = client.get_type("GenerateKeywordIdeasRequest")
        req.customer_id = customer_id
        req.language = lang_path
        req.geo_target_constants.extend(geo_paths)
        req.keyword_plan_network = kp_network

        seed_list: list[str] = []
        if seed:
            seed_list = [s.replace("+", " ").strip() for s in seed.split(",") if s.strip()]

        if seed_list and url:
            req.keyword_and_url_seed.url = url
            req.keyword_and_url_seed.keywords.extend(seed_list)
        elif url:
            req.url_seed.url = url
        elif seed_list:
            req.keyword_seed.keywords.extend(seed_list)
        else:
            raise HTTPException(status_code=400, detail="Provide at least one of: seed or url")

        resp = svc.generate_keyword_ideas(request=req)
        out = []
        for i, r in enumerate(resp):
            if i >= max(1, min(limit, 800)):
                break
            text = getattr(r, "text", None)
            metrics = getattr(r, "keyword_idea_metrics", None)
            if not text or not metrics:
                continue
            out.append({
                "idea": text,
                "avg_monthly_searches": getattr(metrics, "avg_monthly_searches", None),
                "competition": getattr(metrics.competition, "name", None) if getattr(metrics, "competition", None) else None,
                "low_top_of_page_bid": micros_to_currency(getattr(metrics, "low_top_of_page_bid_micros", 0)),
                "high_top_of_page_bid": micros_to_currency(getattr(metrics, "high_top_of_page_bid_micros", 0)),
            })

        log_api_usage(
            scope_id=customer_id,
            request_id=None,
            endpoint="/ads/keyword-ideas",
            request_type="list",
            operations=0,
        )
        return {
            "api_version": _API_VERSION,
            "customer_id": customer_id,
            "geo": geo_ids,
            "language": lang,
            "network": "GOOGLE_SEARCH" if kp_network == kp_enum.GOOGLE_SEARCH else "GOOGLE_SEARCH_AND_PARTNERS",
            "count": len(out),
            "ideas": out,
        }
    except GoogleAdsException as e:
        errors = [
            {"code": err.error_code.WhichOneof("error_code"), "message": err.message}
            for err in e.failure.errors
        ]
        raise HTTPException(status_code=400, detail={"request_id": e.request_id, "errors": errors})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
