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
            if not r:
                return {"ok": False, "error": "No response"}
            return {"ok": True, "database": r.get("db"), "version": r.get("ver")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB ping failed: {e}")


@router.post("/db/pgvector-analyze")
def pgvector_analyze(reindex: bool = False):
    """Run ANALYZE on the embeddings table and optionally REINDEX the ivfflat index.

    - For Postgres only. SQLite is a no-op.
    - REINDEX uses CONCURRENTLY and AUTOCOMMIT to avoid transaction limitations.
    """
    try:
        dialect = engine.dialect.name
        if dialect != "postgresql":
            return {"ok": True, "dialect": dialect, "action": "noop"}
        out = {"ok": True, "dialect": dialect,
               "analyzed": False, "reindexed": False}
        # ANALYZE
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(text("ANALYZE embedding"))
            out["analyzed"] = True
        # Optional REINDEX (CONCURRENTLY)
        if reindex:
            try:
                with engine.connect() as conn:
                    conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                    conn.execute(
                        text("REINDEX INDEX CONCURRENTLY IF EXISTS ix_embedding_vector_ivfflat"))
                    out["reindexed"] = True
            except Exception as re:
                # Non-fatal; report in payload
                out["reindex_error"] = str(re)
        return out
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"pgvector analyze failed: {e}")


@router.post("/db/pgvector-index-alt")
def pgvector_index_alt(action: str = "create", lists: int = 100, name: str | None = None):
    """Create or drop an alternate ivfflat index with a custom `lists` value.

    - action: "create" or "drop"
    - lists: number of inverted lists (10–65535 recommended)
    - name: optional index name (default: ix_embedding_vector_ivfflat_l{lists})
    """
    try:
        dialect = engine.dialect.name
        if dialect != "postgresql":
            return {"ok": True, "dialect": dialect, "action": "noop"}

        # Validate inputs
        lists = int(lists)
        if lists < 10:
            lists = 10
        if lists > 65535:
            lists = 65535
        idx_name = name or f"ix_embedding_vector_ivfflat_l{lists}"
        # Basic safety for index name
        import re
        if not re.fullmatch(r"[A-Za-z0-9_]+", idx_name or ""):
            raise HTTPException(status_code=400, detail="Invalid index name")

        out = {"ok": True, "dialect": dialect,
               "action": action, "index": idx_name, "lists": lists}
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            if action == "create":
                conn.execute(text(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name} ON embedding USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})"))
            elif action == "drop":
                conn.execute(
                    text(f"DROP INDEX CONCURRENTLY IF EXISTS {idx_name}"))
            else:
                raise HTTPException(
                    status_code=400, detail="action must be 'create' or 'drop'")

        # Return current embedding indexes for visibility
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'embedding'
                ORDER BY indexname
            """)).mappings().all()
            out["indexes"] = [{"name": r["indexname"],
                               "def": r["indexdef"]} for r in rows]
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"pgvector index alt failed: {e}")
