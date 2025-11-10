# app/services/usage_log.py
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from ..db.session import SessionLocal
from ..db.models import QuotaUsage

from ..settings import settings

LOG_PATH = Path("api_usage_log.csv")


def log_api_usage(
    *,
    scope_id: str,
    request_id: Optional[str],
    endpoint: str,
    request_type: str,
    operations: int,
) -> None:
    """Deprecated CSV logger retained as no-op to avoid breaking imports."""
    # Intentionally no-op; usage is now persisted via QuotaUsage and summaries.
    return None


def _read_all_rows() -> List[Dict[str, Any]]:
    """Return empty list; CSV log is deprecated."""
    return []


# ---------- Functions expected by app/routers/usage.py ----------

def read_usage_log(limit: int = 100, offset: int = 0, provider: Optional[str] = None, metric: Optional[str] = None, scope_id: Optional[str] = None, endpoint_contains: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return recent quota usage events (provider, metric, amount) as legacy usage rows.

    This replaces the former CSV usage log. Supports pagination via limit/offset.
    """
    limit = max(1, min(int(limit or 1), 1000))
    offset = max(0, int(offset or 0))
    with SessionLocal() as db:
        stmt = select(QuotaUsage)
        if provider:
            stmt = stmt.where(QuotaUsage.provider == provider)
        if metric:
            stmt = stmt.where(QuotaUsage.metric == metric)
        if scope_id:
            stmt = stmt.where(QuotaUsage.scope_id == scope_id)
        if endpoint_contains:
            stmt = stmt.where(QuotaUsage.endpoint.contains(endpoint_contains))
        stmt = stmt.order_by(QuotaUsage.id.desc()).offset(offset).limit(limit)
        events = db.execute(stmt).scalars().all()
    out: List[Dict[str, Any]] = []
    for e in events:
        ts_val = getattr(e, "ts", None)
        ts_iso = ts_val.isoformat() if isinstance(ts_val, datetime) else None
        out.append({
            "ts": ts_iso,
            "scope_id": e.scope_id,
            "request_id": e.request_id,
            "endpoint": e.endpoint,
            "request_type": (e.extra.get("request_type") if isinstance(e.extra, dict) else None) or "n/a",
            "operations": (e.extra.get("operations") if isinstance(e.extra, dict) else None) or e.amount,
            "provider": e.provider,
            "metric": e.metric,
            "amount": e.amount,
        })
    return out


def prune_quota_usage_older_than(days: int) -> int:
    """Delete QuotaUsage rows older than N days. Returns number of rows deleted."""
    from datetime import timedelta
    days = max(1, int(days or 1))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with SessionLocal() as db:
        to_delete = db.execute(
            select(QuotaUsage).where(QuotaUsage.ts < cutoff)
        ).scalars().all()
        count = len(to_delete)
        for row in to_delete:
            db.delete(row)
        db.commit()
        return count


def usage_summary() -> Dict[str, Any]:
    """DB-backed usage summary derived from QuotaUsage events.

    Treat provider 'internal_api' metric 'requests' as GET requests analog.
    Aggregate totals and today's counts; caps from settings.
    """
    get_cap = settings.BASIC_DAILY_GET_REQUEST_LIMIT
    ops_cap = settings.BASIC_DAILY_OPERATION_LIMIT
    today = datetime.now(timezone.utc).date()
    with SessionLocal() as db:
        # Total events
        total_usage_rows = db.execute(
            select(func.count()).select_from(QuotaUsage)).scalar() or 0
        # Total operations approximated by sum(amount) across all metrics except tokens
        total_operations = db.execute(select(func.sum(QuotaUsage.amount)).where(
            ~QuotaUsage.metric.like('%tokens'))).scalar() or 0
        # Total internal API requests
        total_get_requests = db.execute(select(func.count()).where(
            QuotaUsage.provider == 'internal_api', QuotaUsage.metric == 'requests')).scalar() or 0

        # Today filters
        today_usage_rows = db.execute(select(func.count()).where(
            func.date(QuotaUsage.ts) == today)).scalar() or 0
        today_operations = db.execute(select(func.sum(QuotaUsage.amount)).where(func.date(
            QuotaUsage.ts) == today, ~QuotaUsage.metric.like('%tokens'))).scalar() or 0
        today_get_requests = db.execute(select(func.count()).where(func.date(
            QuotaUsage.ts) == today, QuotaUsage.provider == 'internal_api', QuotaUsage.metric == 'requests')).scalar() or 0

    return {
        "total_usage_rows": int(total_usage_rows),
        "total_operations": int(total_operations),
        "total_get_requests": int(total_get_requests),
        "today_usage_rows": int(today_usage_rows),
        "today_get_requests": int(today_get_requests),
        "today_operations": int(today_operations),
        "get_cap": get_cap,
        "ops_cap": ops_cap,
    }


# ---------- Unified quota usage persistence (DB) ----------

def record_quota_event(
    provider: str,
    metric: str,
    amount: int,
    scope_id: Optional[str] = None,
    request_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
) -> None:
    """Persist a quota usage event into the quota_usage table.

    If a Session isn't provided, creates a short-lived one.
    """
    close_after = False
    if db is None:
        db = SessionLocal()
        close_after = True
    try:
        evt = QuotaUsage(
            provider=provider,
            metric=metric,
            amount=int(amount or 0),
            scope_id=scope_id,
            request_id=request_id,
            endpoint=endpoint,
            extra=extra or None,
        )
        # SQLite quirk: AUTOINCREMENT only applies to INTEGER PRIMARY KEY, not BIGINT.
        # Our migration defines BigInteger for Postgres; on SQLite dev fallback we must
        # emulate an auto-increment id manually if dialect is sqlite and id stays None.
        try:
            # type: ignore[attr-defined]
            if getattr(evt, "id", None) is None and db.bind and db.bind.dialect.name == 'sqlite':
                max_id = db.execute(select(func.max(QuotaUsage.id))).scalar()
                setattr(evt, "id", (max_id or 0) + 1)
        except Exception:
            pass
        db.add(evt)
        db.commit()
    except Exception:
        if db is not None:
            db.rollback()
        # Silent failure; optionally hook logging here
    finally:
        if close_after and db is not None:
            db.close()


def quota_usage_summary(provider: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate quota usage counts for quick monitoring.

    If provider is specified, filters to that provider.
    Returns totals grouped by (provider, metric) and today's usage.
    """
    with SessionLocal() as db:
        filters = []
        if provider:
            filters.append(QuotaUsage.provider == provider)

        # Total aggregation
        stmt_total = select(
            QuotaUsage.provider,
            QuotaUsage.metric,
            func.sum(QuotaUsage.amount).label("total"),
        )
        if filters:
            for f in filters:
                stmt_total = stmt_total.where(f)
        stmt_total = stmt_total.group_by(
            QuotaUsage.provider, QuotaUsage.metric)
        totals = db.execute(stmt_total).all()

        # Today's aggregation
        today = datetime.now(timezone.utc).date()
        stmt_today = select(
            QuotaUsage.provider,
            QuotaUsage.metric,
            func.sum(QuotaUsage.amount).label("today_total"),
        )
        stmt_today = stmt_today.where(func.date(QuotaUsage.ts) == today)
        if filters:
            for f in filters:
                stmt_today = stmt_today.where(f)
        stmt_today = stmt_today.group_by(
            QuotaUsage.provider, QuotaUsage.metric)
        todays = db.execute(stmt_today).all()

    return {
        "provider_filter": provider,
        "totals": [
            {"provider": p, "metric": m, "total": int(t)} for (p, m, t) in totals
        ],
        "today": [
            {"provider": p, "metric": m, "total": int(t)} for (p, m, t) in todays
        ],
    }


# ---------- Dashboard helper used by /misc ----------

def dashboard_stats(default_mcc_id: str) -> Dict[str, Any]:
    """Compact stats for the HTML dashboard."""
    s = usage_summary()
    return {
        **s,
        "default_mcc_id": default_mcc_id,
    }
