# app/services/embeddings.py
from __future__ import annotations
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.session import SessionLocal
from ..db.models import Embedding
from .openai_client import embed_texts, hash_text
from .usage_log import record_quota_event


def _chunk_text(text: str, max_words: int = 800, overlap: int = 50) -> List[str]:
    words = text.split()
    if not words:
        return []
    chunks: List[str] = []
    i = 0
    n = len(words)
    while i < n:
        j = min(n, i + max_words)
        chunk = " ".join(words[i:j])
        chunks.append(chunk)
        if j == n:
            break
        i = max(0, j - overlap)
    return chunks


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x, y in zip(a, b))
    na = sqrt(sum(x*x for x in a))
    nb = sqrt(sum(y*y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass
class Retrieved:
    id: int
    entity_type: str
    entity_id: Optional[str]
    scope_id: Optional[str]
    title: Optional[str]
    text: str
    score: float
    meta: Optional[Dict[str, Any]]


def upsert_embeddings_for_entity(
    *,
    entity_type: str,
    entity_id: Optional[str],
    scope_id: Optional[str],
    title: Optional[str],
    text: str,
    model: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    chunk_words: int = 800,
    overlap_words: int = 50,
    db: Optional[Session] = None,
) -> List[int]:
    """Create or update embeddings for a single entity text (chunked).

    Idempotent with text_hash; if unchanged, skip re-embedding.
    Returns list of inserted row IDs.
    """
    close_after = False
    if db is None:
        db = SessionLocal()
        close_after = True
    try:
        chunks = _chunk_text(text, chunk_words, overlap_words)
        if not chunks:
            return []
        # Compute hashes for quick idempotency check
        hashes = [hash_text(c) for c in chunks]
        # Find existing by (entity_type, entity_id, chunk_index) with same hash
        existing = db.execute(
            select(Embedding).where(
                Embedding.entity_type == entity_type,
                Embedding.entity_id == entity_id,
            )
        ).scalars().all()
        by_idx = {(e.chunk_index or 0): e for e in existing}
        to_embed: List[Tuple[int, str]] = []
        for idx, (chunk, h) in enumerate(zip(chunks, hashes)):
            row = by_idx.get(idx)
            if row is not None and getattr(row, "text_hash", None) == h:
                continue  # up to date
            to_embed.append((idx, chunk))
        if not to_embed:
            return [getattr(e, 'id', 0) for e in existing]
        # Generate embeddings
        texts = [t for _, t in to_embed]
        resp = embed_texts(texts, model=model)
        vecs = [d.get('embedding', []) for d in resp.get('data', [])]
        new_ids: List[int] = []
        for (idx, chunk), vec, h in zip(to_embed, vecs, [hash_text(t) for t in texts]):
            row = by_idx.get(idx)
            if row is not None:
                setattr(row, "text", chunk)
                setattr(row, "text_hash", h)
                # pgvector will coerce list -> vector; sqlite stores JSON
                setattr(row, "embedding", vec)
                setattr(row, "model", resp.get('model'))
                setattr(row, "provider", 'openai')
                setattr(row, "title", title)
                setattr(row, "meta", meta)
                setattr(row, "scope_id", scope_id)
            else:
                e = Embedding(
                    provider='openai',
                    model=resp.get('model'),
                    entity_type=entity_type,
                    entity_id=entity_id,
                    scope_id=scope_id,
                    title=title,
                    text=chunk,
                    text_hash=h,
                    chunk_index=idx,
                    meta=meta,
                    embedding=vec,
                    dim=len(vec) if vec else 1536,
                )
                # Manual ID assignment for SQLite (BigInteger autoincrement quirk)
                try:
                    if db.bind and db.bind.dialect.name == 'sqlite' and getattr(e, 'id', None) is None:
                        from sqlalchemy import func, select as _select
                        max_id = db.execute(
                            _select(func.max(Embedding.id))).scalar()
                        setattr(e, 'id', (max_id or 0) + 1)
                except Exception:
                    pass
                db.add(e)
                db.flush()
                new_ids.append(getattr(e, 'id', 0))
        db.commit()
        return new_ids
    finally:
        if close_after:
            db.close()


def search_embeddings(
    *,
    q: str,
    k: int = 8,
    entity_type: Optional[str] = None,
    scope_id: Optional[str] = None,
    model: Optional[str] = None,
    db: Optional[Session] = None,
) -> List[Retrieved]:
    """Vector search: embed query and perform ANN search in DB.

    Falls back to Python cosine similarity when running on SQLite dev.
    """
    from sqlalchemy import and_
    close_after = False
    if db is None:
        db = SessionLocal()
        close_after = True
    try:
        # Generate query embedding
        q_emb = embed_texts([q], model=model)["data"][0]["embedding"]
        # Detect dialect
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        filters = []
        if entity_type:
            filters.append(Embedding.entity_type == entity_type)
        if scope_id:
            filters.append(Embedding.scope_id == scope_id)
        base = select(Embedding)
        if filters:
            base = base.where(and_(*filters))
        if dialect == "sqlite":
            # Fallback: compute cosine in Python on recent rows
            rows = db.execute(base.order_by(Embedding.ts.desc()).limit(
                max(200, k))).scalars().all()
            out: List[Retrieved] = []
            for r in rows:
                vec = getattr(r, "embedding", []) or []
                try:
                    score = _cosine(vec, q_emb) if isinstance(
                        vec, list) else 0.0
                except Exception:
                    score = 0.0
                out.append(Retrieved(
                    id=int(getattr(r, 'id', 0) or 0),
                    entity_type=str(getattr(r, 'entity_type', '') or ''),
                    entity_id=getattr(r, 'entity_id', None),
                    scope_id=getattr(r, 'scope_id', None),
                    title=getattr(r, 'title', None),
                    text=str(getattr(r, 'text', '') or ''),
                    score=float(score),
                    meta=getattr(r, 'meta', None),
                ))
            out.sort(key=lambda x: x.score, reverse=True)
            return out[:k]
        else:
            # Postgres + pgvector: use cosine distance
            # Order by ascending distance (smaller is better); compute score=1-dist for output
            stmt = base.order_by(Embedding.embedding.cosine_distance(
                q_emb)).limit(k)  # type: ignore[attr-defined]
            rows = db.execute(stmt).scalars().all()
            out: List[Retrieved] = []
            for r in rows:
                # No direct distance value returned here without select add; score approximated via recompute client-side if needed
                out.append(Retrieved(
                    id=int(getattr(r, 'id', 0) or 0),
                    entity_type=str(getattr(r, 'entity_type', '') or ''),
                    entity_id=getattr(r, 'entity_id', None),
                    scope_id=getattr(r, 'scope_id', None),
                    title=getattr(r, 'title', None),
                    text=str(getattr(r, 'text', '') or ''),
                    score=0.0,
                    meta=getattr(r, 'meta', None),
                ))
            return out
    finally:
        if close_after:
            db.close()
