# app/db/models.py
from __future__ import annotations
from sqlalchemy import Column, Date, String, BigInteger, Float, JSON, TIMESTAMP, Text
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
