# app/db/session.py
from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..settings import settings

_DB_URL = settings.DATABASE_URL or os.getenv("DATABASE_URL")
if not _DB_URL:
    # Use project-local sqlite file so Alembic/dev share the same DB
    _DB_URL = "sqlite:///./dev.db"  # fallback for dev tests without Neon

# Normalize Postgres driver to psycopg for SQLAlchemy 2.x if not specified
if _DB_URL.startswith("postgresql://") and "+psycopg" not in _DB_URL:
    _DB_URL = _DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(_DB_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False, future=True)


def get_db():
    from contextlib import contextmanager
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
