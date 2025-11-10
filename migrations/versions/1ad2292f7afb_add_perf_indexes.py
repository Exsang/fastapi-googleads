"""add perf indexes

Revision ID: 1ad2292f7afb
Revises: a6b703e38e55
Create Date: 2025-11-10 22:39:37.686637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ad2292f7afb'
down_revision: Union[str, Sequence[str], None] = 'a6b703e38e55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add helpful indexes for common queries."""
    # Generic index to speed date + level + customer filters
    op.create_index(
        "ix_ads_daily_perf_date_level_cust",
        "ads_daily_perf",
        ["perf_date", "level", "customer_id"],
        unique=False,
    )

    # Partial indexes per level for targeted lookups
    op.create_index(
        "ix_ads_daily_perf_campaign",
        "ads_daily_perf",
        ["customer_id", "perf_date", "campaign_id"],
        unique=False,
        postgresql_where=sa.text("level = 'campaign'"),
    )
    op.create_index(
        "ix_ads_daily_perf_ad_group",
        "ads_daily_perf",
        ["customer_id", "perf_date", "ad_group_id"],
        unique=False,
        postgresql_where=sa.text("level = 'ad_group'"),
    )
    op.create_index(
        "ix_ads_daily_perf_ad",
        "ads_daily_perf",
        ["customer_id", "perf_date", "ad_id"],
        unique=False,
        postgresql_where=sa.text("level = 'ad'"),
    )
    op.create_index(
        "ix_ads_daily_perf_keyword",
        "ads_daily_perf",
        ["customer_id", "perf_date", "criterion_id"],
        unique=False,
        postgresql_where=sa.text("level = 'keyword'"),
    )


def downgrade() -> None:
    """Downgrade schema: drop indexes."""
    op.drop_index("ix_ads_daily_perf_keyword", table_name="ads_daily_perf")
    op.drop_index("ix_ads_daily_perf_ad", table_name="ads_daily_perf")
    op.drop_index("ix_ads_daily_perf_ad_group", table_name="ads_daily_perf")
    op.drop_index("ix_ads_daily_perf_campaign", table_name="ads_daily_perf")
    op.drop_index("ix_ads_daily_perf_date_level_cust",
                  table_name="ads_daily_perf")
