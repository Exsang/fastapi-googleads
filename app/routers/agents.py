# app/routers/agents.py
from __future__ import annotations
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime

from ..deps.auth import require_auth
from ..db.session import SessionLocal
from ..db.agent_models import AgentProposal, AgentDecision, ensure_agent_schema

router = APIRouter(
    prefix="/agents", tags=["agents"], dependencies=[Depends(require_auth)])


class ProposalIn(BaseModel):
    agent: str = Field(...,
                       description="proposing agent id, e.g., 'keyword_mining'")
    scope_id: str = Field(..., description="CID or MCC")
    proposal_type: str = Field(...,
                               description="add_keyword|negative_keyword|adjust_budget|...")
    payload: dict
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


@router.post("/proposals")
def create_proposal(p: ProposalIn):
    ensure_agent_schema()
    db = SessionLocal()
    try:
        obj = AgentProposal(
            agent=p.agent,
            scope_id=p.scope_id,
            proposal_type=p.proposal_type,
            payload=p.payload,
            rationale=p.rationale,
            confidence=p.confidence,
            status="proposed",
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return {"ok": True, "id": obj.id}
    finally:
        db.close()


class DecisionIn(BaseModel):
    action: Literal["approve", "reject", "execute", "measure"]
    actor: str
    notes: Optional[str] = None
    meta: Optional[dict] = None


@router.post("/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: int, d: DecisionIn):
    ensure_agent_schema()
    db = SessionLocal()
    try:
        prop: AgentProposal | None = db.get(AgentProposal, proposal_id)
        if not prop:
            raise HTTPException(status_code=404, detail="proposal not found")

        # record decision
        rec = AgentDecision(
            proposal_id=proposal_id,
            actor=d.actor,
            action=d.action,
            notes=d.notes,
            meta=d.meta,
        )
        db.add(rec)

        # state machine (minimal)
        now = datetime.utcnow()
        # Direct attribute assignment on SQLAlchemy instances; type: ignore hints silence static checkers
        if d.action == "approve":  # type: ignore[assignment]
            setattr(prop, "status", "approved")
            setattr(prop, "approved_by", d.actor)
            setattr(prop, "approved_ts", now)
        elif d.action == "reject":  # type: ignore[assignment]
            setattr(prop, "status", "rejected")
        elif d.action == "execute":  # type: ignore[assignment]
            # here we'd call mutate APIs (future); for now, mark executed
            setattr(prop, "status", "executed")
            setattr(prop, "executed_ts", now)
        elif d.action == "measure":  # type: ignore[assignment]
            setattr(prop, "status", "measured")
            setattr(prop, "measured_ts", now)

        db.commit()
        return {"ok": True, "proposal_id": proposal_id, "status": prop.status}
    finally:
        db.close()


@router.get("/proposals")
def list_proposals(
    scope_id: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    ensure_agent_schema()
    db = SessionLocal()
    try:
        from sqlalchemy import select, and_, func as _f
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        stmt = select(AgentProposal)
        filters = []
        if scope_id:
            filters.append(AgentProposal.scope_id == scope_id)
        if status:
            filters.append(AgentProposal.status == status)
        if agent:
            filters.append(AgentProposal.agent == agent)
        if filters:
            stmt = stmt.where(and_(*filters))
        # Count total with same filters
        count_stmt = select(_f.count()).select_from(AgentProposal)
        if filters:
            count_stmt = count_stmt.where(and_(*filters))
        total = db.execute(count_stmt).scalar_one()

        stmt = stmt.order_by(AgentProposal.ts.desc()
                             ).offset(offset).limit(limit)
        seq = db.execute(stmt).scalars().all()
        rows = list(seq)

        def _ts_iso(x):
            try:
                return x.isoformat() if x is not None else None
            except Exception:
                return None
        items = [
            {
                "id": getattr(r, "id", None),
                "ts": _ts_iso(getattr(r, "ts", None)),
                "agent": getattr(r, "agent", None),
                "scope_id": getattr(r, "scope_id", None),
                "type": getattr(r, "proposal_type", None),
                "status": getattr(r, "status", None),
                "confidence": getattr(r, "confidence", None),
            }
            for r in rows
        ]
        return {"total": int(total or 0), "limit": limit, "offset": offset, "items": items}
    finally:
        db.close()


@router.post("/proposals/bulk-decision")
def bulk_decision(
    action: Literal["approve", "reject", "execute", "measure"],
    scope_id: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    actor: str = "ui",
    notes: Optional[str] = None,
):
    """Apply the same decision to a filtered set of proposals.

    Warning: Use filters to constrain the set (e.g., scope_id + status=proposed).
    Returns number of affected rows and sample IDs.
    """
    ensure_agent_schema()
    db = SessionLocal()
    try:
        from sqlalchemy import select, and_
        stmt = select(AgentProposal)
        filters = []
        if scope_id:
            filters.append(AgentProposal.scope_id == scope_id)
        if status:
            filters.append(AgentProposal.status == status)
        if agent:
            filters.append(AgentProposal.agent == agent)
        if filters:
            stmt = stmt.where(and_(*filters))
        seq = db.execute(stmt).scalars().all()
        ids = [getattr(r, "id", None)
               for r in seq if getattr(r, "id", None) is not None]
        now = datetime.utcnow()
        affected = 0
        for prop in seq:
            rec = AgentDecision(
                proposal_id=prop.id, actor=actor, action=action, notes=notes, meta=None
            )
            db.add(rec)
            if action == "approve":
                setattr(prop, "status", "approved")
                setattr(prop, "approved_by", actor)
                setattr(prop, "approved_ts", now)
            elif action == "reject":
                setattr(prop, "status", "rejected")
            elif action == "execute":
                setattr(prop, "status", "executed")
                setattr(prop, "executed_ts", now)
            elif action == "measure":
                setattr(prop, "status", "measured")
                setattr(prop, "measured_ts", now)
            affected += 1
        db.commit()
        return {"ok": True, "affected": affected, "ids": ids[:50]}
    finally:
        db.close()


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: int):
    """Return full proposal details including rationale and payload."""
    ensure_agent_schema()
    db = SessionLocal()
    try:
        r: AgentProposal | None = db.get(AgentProposal, proposal_id)
        if not r:
            raise HTTPException(status_code=404, detail="not found")

        def _ts_iso(x):
            try:
                return x.isoformat() if x is not None else None
            except Exception:
                return None
        return {
            "id": getattr(r, "id", None),
            "ts": _ts_iso(getattr(r, "ts", None)),
            "agent": getattr(r, "agent", None),
            "scope_id": getattr(r, "scope_id", None),
            "type": getattr(r, "proposal_type", None),
            "status": getattr(r, "status", None),
            "confidence": getattr(r, "confidence", None),
            "rationale": getattr(r, "rationale", None),
            "payload": getattr(r, "payload", None),
            "baseline_metrics": getattr(r, "baseline_metrics", None),
            "outcome_metrics": getattr(r, "outcome_metrics", None),
            "approved_by": getattr(r, "approved_by", None),
            "approved_ts": _ts_iso(getattr(r, "approved_ts", None)),
            "executed_ts": _ts_iso(getattr(r, "executed_ts", None)),
            "measured_ts": _ts_iso(getattr(r, "measured_ts", None)),
            "error": getattr(r, "error", None),
        }
    finally:
        db.close()


@router.get("/decisions")
def list_decisions(proposal_id: Optional[int] = None, scope_id: Optional[str] = None, limit: int = 100, offset: int = 0):
    """Activity log: list decisions with optional filters."""
    ensure_agent_schema()
    db = SessionLocal()
    try:
        from sqlalchemy import select, and_, func as _f
        from sqlalchemy.orm import aliased
        limit = max(1, min(limit, 1000))
        offset = max(0, offset)
        stmt = select(AgentDecision)
        if proposal_id:
            stmt = stmt.where(AgentDecision.proposal_id == proposal_id)
        if scope_id:
            # join to proposals to filter by scope
            P = aliased(AgentProposal)
            stmt = select(AgentDecision).join(
                P, P.id == AgentDecision.proposal_id).where(P.scope_id == scope_id)
        # Count total
        count_stmt = select(_f.count()).select_from(stmt.subquery())
        total = db.execute(count_stmt).scalar_one()
        stmt = stmt.order_by(AgentDecision.ts.desc()
                             ).offset(offset).limit(limit)
        seq = db.execute(stmt).scalars().all()
        rows = list(seq)

        def _ts_iso(x):
            try:
                return x.isoformat() if x is not None else None
            except Exception:
                return None
        items = [
            {
                "id": getattr(r, "id", None),
                "ts": _ts_iso(getattr(r, "ts", None)),
                "proposal_id": getattr(r, "proposal_id", None),
                "actor": getattr(r, "actor", None),
                "action": getattr(r, "action", None),
                "notes": getattr(r, "notes", None),
            }
            for r in rows
        ]
        return {"total": int(total or 0), "limit": limit, "offset": offset, "items": items}
    finally:
        db.close()
