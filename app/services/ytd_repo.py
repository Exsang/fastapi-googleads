# app/services/ytd_repo.py
from __future__ import annotations
import os
from datetime import date
from typing import Iterable, Optional, List, Dict, Any

from sqlalchemy import (
    create_engine, Column, Date, String, BigInteger, Float, Integer,
    UniqueConstraint, select
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

try:
    # SQLAlchemy 2.x recommended
    from sqlalchemy.orm import Mapped, mapped_column
    HAS_MAPPED = True
except Exception:
    HAS_MAPPED = False

# --- Engine / Session bootstrap ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
os.makedirs(os.path.dirname(DATABASE_URL.replace("sqlite:///", "")), exist_ok=True) if DATABASE_URL.startswith("sqlite:///") else None

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

# --- ORM model ---
if HAS_MAPPED:
    class YTDDaily(Base):
        __tablename__ = "ytd_daily"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
        customer_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
        campaign_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

        impressions: Mapped[int] = mapped_column(BigInteger, default=0)
        clicks: Mapped[int] = mapped_column(BigInteger, default=0)
        cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
        conversions: Mapped[float] = mapped_column(Float, default=0.0)
        conversion_value: Mapped[float] = mapped_column(Float, default=0.0)

        __table_args__ = (
            UniqueConstraint("day", "customer_id", "campaign_id", name="uq_ytd_daily_row"),
        )
else:
    # Fallback for SQLAlchemy 1.4 style (if needed)
    class YTDDaily(Base):
        __tablename__ = "ytd_daily"
        id = Column(Integer, primary_key=True, autoincrement=True)
        day = Column(Date, nullable=False, index=True)
        customer_id = Column(String(32), nullable=False, index=True)
        campaign_id = Column(String(64), nullable=True, index=True)

        impressions = Column(BigInteger, default=0)
        clicks = Column(BigInteger, default=0)
        cost_micros = Column(BigInteger, default=0)
        conversions = Column(Float, default=0.0)
        conversion_value = Column(Float, default=0.0)

        __table_args__ = (
            UniqueConstraint("day", "customer_id", "campaign_id", name="uq_ytd_daily_row"),
        )

def ensure_schema() -> None:
    """Create table if it does not exist."""
    Base.metadata.create_all(engine)

def upsert_rows(rows: Iterable[Dict[str, Any]]) -> int:
    """
    Idempotent upsert via session.merge(...) per row.
    Works across SQLite and Postgres without dialect-specific syntax.
    Each row must include: day, customer_id, campaign_id (+metrics)
    """
    ensure_schema()
    count = 0
    with SessionLocal() as db:
        for r in rows:
            # Use a natural key by querying first, then set fields
            stmt = select(YTDDaily).where(
                YTDDaily.day == r["day"],
                YTDDaily.customer_id == r["customer_id"],
                YTDDaily.campaign_id == r.get("campaign_id")
            )
            existing = db.execute(stmt).scalars().first()
            if existing:
                existing.impressions = int(r.get("impressions", 0) or 0)
                existing.clicks = int(r.get("clicks", 0) or 0)
                existing.cost_micros = int(r.get("cost_micros", 0) or 0)
                existing.conversions = float(r.get("conversions", 0.0) or 0.0)
                existing.conversion_value = float(r.get("conversion_value", 0.0) or 0.0)
            else:
                obj = YTDDaily(
                    day=r["day"],
                    customer_id=str(r["customer_id"]),
                    campaign_id=str(r["campaign_id"]) if r.get("campaign_id") not in (None, "", "None") else None,
                    impressions=int(r.get("impressions", 0) or 0),
                    clicks=int(r.get("clicks", 0) or 0),
                    cost_micros=int(r.get("cost_micros", 0) or 0),
                    conversions=float(r.get("conversions", 0.0) or 0.0),
                    conversion_value=float(r.get("conversion_value", 0.0) or 0.0),
                )
                db.add(obj)
            count += 1
        db.commit()
    return count

def fetch_rows_from_db(customer_id: str, campaign_id: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_schema()
    with SessionLocal() as db:
        stmt = select(YTDDaily).where(YTDDaily.customer_id == str(customer_id))
        if campaign_id is not None:
            stmt = stmt.where(YTDDaily.campaign_id == str(campaign_id))
        stmt = stmt.order_by(YTDDaily.day.asc(), YTDDaily.campaign_id.asc())
        out: List[Dict[str, Any]] = []
        for row in db.execute(stmt).scalars():
            out.append({
                "day": row.day.isoformat(),
                "customer_id": row.customer_id,
                "campaign_id": row.campaign_id,
                "impressions": row.impressions,
                "clicks": row.clicks,
                "cost_micros": row.cost_micros,
                "conversions": row.conversions,
                "conversion_value": row.conversion_value,
            })
        return out
