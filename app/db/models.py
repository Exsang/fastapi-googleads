# app/db/models.py
from __future__ import annotations
from sqlalchemy import Column, Date, String, BigInteger, Float, JSON, TIMESTAMP, Text, Integer
try:
    from pgvector.sqlalchemy import Vector  # type: ignore
except Exception:  # pragma: no cover
    Vector = None  # type: ignore
from sqlalchemy.sql import func
from .base import Base

# Dimension tables (minimal fields; extend as needed)


class AdsCustomer(Base):
    __tablename__ = "ads_customer"
    customer_id = Column(String, primary_key=True)
    descriptive_name = Column(String)
    currency_code = Column(String(10))
    time_zone = Column(String(64))
    # store 'TRUE'/'FALSE' from API or normalize later
    manager = Column(String(5))
    status = Column(String(32))
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now())


class AdsCampaign(Base):
    __tablename__ = "ads_campaign"
    campaign_id = Column(String, primary_key=True)
    customer_id = Column(String, index=True)
    name = Column(String)
    status = Column(String(32))
    channel_type = Column(String(64))
    bidding_strategy_type = Column(String(64))
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now())


class AdsAdGroup(Base):
    __tablename__ = "ads_ad_group"
    ad_group_id = Column(String, primary_key=True)
    campaign_id = Column(String, index=True)
    name = Column(String)
    status = Column(String(32))
    type = Column(String(64))
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now())


class AdsAd(Base):
    __tablename__ = "ads_ad"
    ad_id = Column(String, primary_key=True)
    ad_group_id = Column(String, index=True)
    type = Column(String(64))
    status = Column(String(32))
    final_urls = Column(JSON)
    headline = Column(Text)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now())


class AdsKeyword(Base):
    __tablename__ = "ads_keyword"
    criterion_id = Column(String, primary_key=True)
    ad_group_id = Column(String, index=True)
    text = Column(String)
    match_type = Column(String(32))
    status = Column(String(32))
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now())

# Daily performance fact table


class AdsDailyPerf(Base):
    __tablename__ = "ads_daily_perf"
    perf_date = Column(Date, primary_key=True)
    level = Column(String(16), primary_key=True)
    customer_id = Column(String, primary_key=True)
    campaign_id = Column(String, primary_key=True, nullable=True)
    ad_group_id = Column(String, primary_key=True, nullable=True)
    ad_id = Column(String, primary_key=True, nullable=True)
    criterion_id = Column(String, primary_key=True, nullable=True)

    impressions = Column(BigInteger)
    clicks = Column(BigInteger)
    cost_micros = Column(BigInteger)
    conversions = Column(Float)
    conversions_value = Column(Float)
    interactions = Column(BigInteger)
    interaction_rate = Column(Float)
    ctr = Column(Float)
    average_cpc_micros = Column(BigInteger)
    average_cpm_micros = Column(BigInteger)
    engagements = Column(BigInteger)
    engagement_rate = Column(Float)
    video_views = Column(BigInteger)
    video_view_rate = Column(Float)
    all_conversions = Column(Float)
    all_conversions_value = Column(Float)

    metrics_json = Column(JSON)
    request_id = Column(String)
    pulled_at = Column(TIMESTAMP, server_default=func.now())


# Quota usage events (provider-agnostic)
class QuotaUsage(Base):
    __tablename__ = "quota_usage"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ts = Column(TIMESTAMP, server_default=func.now(), index=True)
    # e.g., 'google_ads', 'openai', 'internal'
    provider = Column(String(64), index=True)
    # e.g., 'requests', 'api_units', 'input_tokens', 'output_tokens'
    metric = Column(String(64), index=True)
    amount = Column(BigInteger, default=0)
    # customer_id, account, etc.
    scope_id = Column(String, index=True, nullable=True)
    request_id = Column(String, nullable=True)
    endpoint = Column(String, nullable=True)
    extra = Column(JSON, nullable=True)


# Embeddings store (for GPT retrieval / RAG)
class Embedding(Base):
    __tablename__ = "embedding"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    provider = Column(String(64), index=True)  # e.g. 'openai'
    model = Column(String(128), index=True)
    # campaign|ad_group|ad|keyword|prompt|doc
    entity_type = Column(String(32), index=True)
    entity_id = Column(String(128), index=True, nullable=True)
    scope_id = Column(String(64), index=True,
                      nullable=True)  # MCC/CID or 'global'
    title = Column(String(512), nullable=True)
    text = Column(Text)  # source content (may be chunk)
    # sha256(content) for idempotency
    text_hash = Column(String(64), index=True)
    # ordering for chunked content
    chunk_index = Column(Integer, nullable=True)
    meta = Column(JSON, nullable=True)  # JSON metadata (metrics, tags)
    # Vector column (dimension fixed by chosen embedding model, e.g., 1536 for text-embedding-3-small)
    # Use pgvector Vector when available (Postgres). Under SQLite dev fallback, store JSON array in 'embedding_json'.
    if Vector is not None:
        embedding = Column(Vector(1536))  # type: ignore[arg-type]
    else:  # pragma: no cover
        embedding = Column(JSON)
    dim = Column(Integer, default=1536)
    ts = Column(TIMESTAMP, server_default=func.now(), index=True)
