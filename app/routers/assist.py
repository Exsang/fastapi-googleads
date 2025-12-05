from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

# Use the same dependency as your other routers
from app.deps.auth import require_auth
from app.services.openai_client import chat_once, stream_chat
from app.services.embeddings import search_embeddings, backfill_search_terms_for_customer
from app.services.embeddings import reembed_stale

router = APIRouter(prefix="/assist", tags=["assist"])


class Message(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    system: Optional[str] = None
    model: Optional[str] = None
    stream: bool = False
    extra: Optional[Dict[str, Any]] = None  # forwarded to Responses API


@router.post("/chat", dependencies=[Depends(require_auth)])
async def chat(req: ChatRequest):
    # keep only user/assistant messages; system is passed separately
    msgs = [m.model_dump()
            for m in req.messages if m.role in ("user", "assistant")]

    if req.stream:
        async def generator():
            async for token in stream_chat(
                messages=msgs,
                system=req.system,
                model=req.model,
                extra=req.extra
            ):
                yield token
        return StreamingResponse(generator(), media_type="text/plain")
    else:
        data = await chat_once(
            messages=msgs,
            system=req.system,
            model=req.model,
            extra=req.extra
        )
        return JSONResponse({"text": data["text"], "model": data["model"], "raw": data["raw"]})


@router.get("/search", dependencies=[Depends(require_auth)])
async def assist_search(request: Request, q: str = "", k: int = 8, entity_type: str | None = None, scope_id: str | None = None, format: str | None = None):
    """Vector search over embeddings store.

    Returns JSON by default. Provide `?format=html` or `Accept: text/html` for a simple HTML UI.
    """
    matches = search_embeddings(
        q=q, k=k, entity_type=entity_type, scope_id=scope_id) if (q or "").strip() else []
    data = {
        "q": q,
        "k": k,
        "entity_type": entity_type,
        "scope_id": scope_id,
        "results": [
            {
                "id": m.id,
                "entity_type": m.entity_type,
                "entity_id": m.entity_id,
                "scope_id": m.scope_id,
                "title": m.title,
                "text": m.text,
                "score": m.score,
                "meta": m.meta,
            }
            for m in matches
        ],
    }
    want_html = (format == 'html') or (
        'text/html' in request.headers.get('accept', '').lower())
    if not want_html:
        return data
    # Basic Tailwind-esque utility classes inline (no CDN to keep self-contained)
    rows_html = "".join([
        f"<div style='padding:8px;border:1px solid #ddd;border-radius:6px;margin-bottom:10px;background:#fafafa'>"
        f"<div style='font-size:13px;color:#555;margin-bottom:4px'>#{i+1} • {r['entity_type']} • score: {r['score']:.4f}</div>"
        f"<div style='font-weight:600;margin-bottom:4px'>{(r['title'] or r['entity_id'] or 'Untitled')}</div>"
        f"<div style='font-size:12px;line-height:1.4;white-space:pre-wrap'>{r['text']}</div>"
        f"<div style='font-size:11px;color:#666;margin-top:6px'>meta: {r['meta']}</div>"
        "</div>"
        for i, r in enumerate(data['results'])
    ]) or "<p style='color:#666'>No results.</p>"
    html = f"""
    <html><head><title>Assist Search</title></head>
    <body style='font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:900px;margin:24px auto;padding:0 16px'>
    <h1 style='font-size:20px;margin-bottom:12px;'>Assist Embedding Search</h1>
    <form method='get' action='/assist/search' style='display:grid;grid-template-columns:1fr 160px 160px 160px 100px;gap:8px;margin-bottom:18px'>
      <input type='text' name='q' value='{q}' placeholder='query text' style='padding:8px;border:1px solid #bbb;border-radius:6px'>
      <input type='text' name='scope_id' value='{scope_id or ''}' placeholder='scope_id (CID)' style='padding:8px;border:1px solid #bbb;border-radius:6px'>
      <input type='text' name='entity_type' value='{entity_type or ''}' placeholder='entity_type' style='padding:8px;border:1px solid #bbb;border-radius:6px'>
      <input type='number' name='k' value='{k}' min='1' max='50' style='padding:8px;border:1px solid #bbb;border-radius:6px'>
      <input type='hidden' name='format' value='html'>
      <button type='submit' style='padding:8px 12px;border:1px solid #444;border-radius:6px;background:#222;color:#fff;'>Search</button>
    </form>
    <div style='margin-bottom:10px;font-size:12px;color:#444'>Results: {len(data['results'])} (q='{q}', k={k}, entity_type='{entity_type}', scope_id='{scope_id}')</div>
    {rows_html}
    <footer style='margin-top:40px;font-size:11px;color:#777'>/assist/search HTML view • JSON available without format=html</footer>
    </body></html>
    """
    return HTMLResponse(html)


@router.post("/backfill-search-terms", dependencies=[Depends(require_auth)])
async def backfill_search_terms(customer_id: str, days: int = 30, limit: int | None = None, model: str | None = None):
    """Fetch recent search terms for a CID and embed them as entity_type='search_term'."""
    result = backfill_search_terms_for_customer(
        customer_id=customer_id, days=days, limit=limit, model=model)
    return result


# ---- Simple RAG answer endpoint ----

class AnswerRequest(BaseModel):
    q: str
    k: int = 6
    entity_type: Optional[str] = None
    scope_id: Optional[str] = None
    model: Optional[str] = None


@router.post("/answer", dependencies=[Depends(require_auth)])
async def assist_answer(req: AnswerRequest):
    """Answer a question using retrieval-augmented generation from embeddings.

    Returns: { ok: bool, answer: str, model: str, contexts: [...], used: {k, entity_type, scope_id} }
    """
    q = (req.q or "").strip()
    if not q:
        return JSONResponse({"ok": False, "error": "q is required"}, status_code=400)
    matches = search_embeddings(
        q=q, k=req.k, entity_type=req.entity_type, scope_id=req.scope_id)
    # Build compact context blocks
    blocks = []
    for m in matches:
        text = (m.text or "").strip()
        if len(text) > 800:
            text = text[:800] + "…"
        meta = m.meta or {}
        blocks.append(
            f"- [{m.entity_type}] {m.title or m.entity_id or ''} (score {m.score:.3f})\n  {text}\n  meta: {meta}")
    context = "\n".join(blocks) if blocks else "(no retrieved context)"
    system = (
        "You are a helpful assistant for Google Ads analytics. "
        "Use the provided context snippets if relevant. "
        "Be concise and factual. If the answer cannot be derived from context and general knowledge, say you don't know."
    )
    user = f"Question: {q}\n\nContext:\n{context}"
    data = await chat_once(messages=[{"role": "user", "content": user}], system=system, model=req.model)
    return {
        "ok": True,
        "answer": data.get("text", ""),
        "model": data.get("model"),
        "contexts": [
            {
                "id": m.id,
                "entity_type": m.entity_type,
                "entity_id": m.entity_id,
                "scope_id": m.scope_id,
                "title": m.title,
                "score": m.score,
            }
            for m in matches
        ],
        "used": {"k": req.k, "entity_type": req.entity_type, "scope_id": req.scope_id},
    }


class ReembedRequest(BaseModel):
    max_age_hours: int = 24
    limit: int = 200
    model: Optional[str] = None
    entity_type: Optional[str] = None
    scope_id: Optional[str] = None
    force: bool = False


@router.post("/reembed", dependencies=[Depends(require_auth)])
async def assist_reembed(req: ReembedRequest):
    """Re-embed stale embeddings.

    Criteria: ts older than max_age_hours (unless force=True) and optional filters.
    Returns summary with counts and sample IDs.
    """
    summary = reembed_stale(
        max_age_hours=req.max_age_hours,
        limit=req.limit,
        model=req.model,
        entity_type=req.entity_type,
        scope_id=req.scope_id,
        force=req.force,
    )
    return summary


# ---- Lightweight config/introspection endpoint for re-embed loop ----
@router.get("/reembed-config", dependencies=[Depends(require_auth)])
async def reembed_config():
    """Return current environment-driven configuration for the background re-embed loop.

    Mirrors logic in `app.main` lifespan setup so operators can inspect live settings.
    Includes a projected daily capacity estimate (ticks_per_day * limit).
    """
    import os
    import math
    import datetime as _dt
    enabled = os.getenv("REEMBED_ENABLED", "true").lower() in {
        "1", "true", "yes"}
    # Interval precedence: explicit minutes, else hours, else default 360 min (6h)
    raw_minutes = os.getenv("REEMBED_INTERVAL_MINUTES", "").strip()
    interval_minutes = int(raw_minutes) if raw_minutes.isdigit() and int(raw_minutes) > 0 else (
        60 * int(os.getenv("REEMBED_INTERVAL_HOURS", "0") or 0) or 360
    )
    limit = int(os.getenv("REEMBED_LIMIT", "150") or 150)
    max_age_hours = int(os.getenv("REEMBED_MAX_AGE_HOURS", "24") or 24)
    entity_type = os.getenv("REEMBED_ENTITY_TYPE") or None
    scope_id = os.getenv("REEMBED_SCOPE_ID") or None
    ticks_per_day = math.floor(
        1440 / interval_minutes) if interval_minutes > 0 else 0
    projected_daily_rows = ticks_per_day * limit if enabled else 0
    # simplistic (not tracking last run timestamp here)
    next_run_eta_minutes = interval_minutes
    return {
        "enabled": enabled,
        "interval_minutes": interval_minutes,
        "limit": limit,
        "max_age_hours": max_age_hours,
        "entity_type": entity_type,
        "scope_id": scope_id,
        "ticks_per_day": ticks_per_day,
        "projected_daily_rows": projected_daily_rows,
        "next_run_eta_minutes": next_run_eta_minutes,
        "now_utc": _dt.datetime.utcnow().isoformat() + "Z",
    }
