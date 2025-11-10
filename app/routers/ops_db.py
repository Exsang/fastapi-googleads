# app/routers/ops_db.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from ..deps.auth import require_auth
from ..db.session import engine

router = APIRouter(
    prefix="/ops", tags=["ops"], dependencies=[Depends(require_auth)])


@router.get("/db/ping")
def db_ping():
    try:
        with engine.connect() as conn:
            r = conn.execute(
                text("select current_database() as db, version() as ver")).mappings().first()
            return {"ok": True, "database": r["db"], "version": r["ver"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB ping failed: {e}")
