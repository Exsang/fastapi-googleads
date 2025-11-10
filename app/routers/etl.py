# app/routers/etl.py
from __future__ import annotations
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..deps.auth import require_auth
from ..db.session import get_db
from ..db.models import AdsDailyPerf
from ..services.etl_google_ads import ingest_campaign_day, ingest_multi_level_day

router = APIRouter(
    prefix="/etl", tags=["etl"], dependencies=[Depends(require_auth)])


@router.get("/ping")
def etl_ping():
    return {"ok": True, "service": "etl"}


@router.post("/run-day")
def run_day(customer_id: str, day: str, levels: str | None = None, db: Session = Depends(get_db)):
    try:
        dt = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    try:
        # If levels param provided (comma-separated), use multi-level ingestion
        if levels:
            level_list = [l.strip() for l in levels.split(',') if l.strip()]
            result = ingest_multi_level_day(db, customer_id, dt, level_list)
        else:
            result = ingest_campaign_day(db, customer_id, dt)
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"ETL failed: {e}")


@router.get("/missing-days")
def missing_days(
    customer_id: str,
    start: str,
    end: str,
    level: str = "campaign",
    db: Session = Depends(get_db),
):
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be >= start")

    stmt = (
        select(AdsDailyPerf.perf_date)
        .where(AdsDailyPerf.customer_id == customer_id)
        .where(AdsDailyPerf.level == level)
        .where(AdsDailyPerf.perf_date >= start_d)
        .where(AdsDailyPerf.perf_date <= end_d)
        .distinct()
    )
    rows = db.execute(stmt).scalars().all()
    present = {d for d in rows}
    missing = []
    cur = start_d
    while cur <= end_d:
        if cur not in present:
            missing.append(cur.isoformat())
        cur += timedelta(days=1)
    return {
        "ok": True,
        "customer_id": customer_id,
        "level": level,
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "missing": missing,
        "present_count": len(present),
    }
