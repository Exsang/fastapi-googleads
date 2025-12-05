# app/db/agent_models.py
"""Agent proposal & decision models.

Purpose:
- Store proposed optimization actions (add keyword, negative, budget change, etc.)
- Track approval and execution lifecycle for safe multi-agent orchestration.

Lifecycle states:
  proposed -> approved -> executed -> measured (optional)

We keep this separated from core ads models to reduce coupling and allow iteration.
"""
from __future__ import annotations
from sqlalchemy import Column, String, BigInteger, JSON, TIMESTAMP, Integer, Text, Float
from sqlalchemy.sql import func
from .base import Base
from .session import engine


class AgentProposal(Base):
    __tablename__ = "agent_proposal"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ts = Column(TIMESTAMP, server_default=func.now(), index=True)
    # agent that created it (e.g., 'keyword_mining', 'budget_pacing')
    agent = Column(String(64), index=True)
    scope_id = Column(String(64), index=True)  # CID or MCC
    # e.g. 'add_keyword', 'negative_keyword', 'adjust_budget'
    proposal_type = Column(String(64), index=True)
    payload = Column(JSON)  # structured data required to execute
    rationale = Column(Text)  # human-readable justification
    confidence = Column(Float)  # 0..1 estimated confidence / expected uplift
    # proposed|approved|rejected|executed|measured
    status = Column(String(24), index=True, default='proposed')
    approved_by = Column(String(128), nullable=True)
    approved_ts = Column(TIMESTAMP, nullable=True)
    executed_ts = Column(TIMESTAMP, nullable=True)
    measured_ts = Column(TIMESTAMP, nullable=True)
    # metrics snapshot at approval/execution time for delta comparison
    baseline_metrics = Column(JSON, nullable=True)
    outcome_metrics = Column(JSON, nullable=True)  # filled post-measurement
    error = Column(Text, nullable=True)


class AgentDecision(Base):
    __tablename__ = "agent_decision"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ts = Column(TIMESTAMP, server_default=func.now(), index=True)
    proposal_id = Column(BigInteger, index=True)
    actor = Column(String(64), index=True)  # orchestrator / human / auto
    action = Column(String(32), index=True)  # approve|reject|execute|measure
    notes = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)


def ensure_agent_schema() -> None:
    """Create agent tables if they do not exist (dev convenience).

    In production, prefer Alembic migrations; this keeps local dev unblocked.
    """
    try:
        # Use the specific Table objects to avoid creating unrelated tables
        from sqlalchemy import Table
        tables: list[Table] = [AgentProposal.__table__,
                               # type: ignore[attr-defined]
                               AgentDecision.__table__]
        Base.metadata.create_all(bind=engine, tables=tables)
    except Exception:
        # Non-fatal; endpoints will error if DDL is disallowed
        pass
