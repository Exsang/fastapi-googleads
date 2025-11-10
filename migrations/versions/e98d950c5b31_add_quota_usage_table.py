"""add quota_usage table

Revision ID: e98d950c5b31
Revises: 1ad2292f7afb
Create Date: 2025-11-10 22:55:33.242814

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e98d950c5b31'
down_revision: Union[str, Sequence[str], None] = '1ad2292f7afb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create quota_usage table and indexes."""
    op.create_table(
        'quota_usage',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('ts', sa.TIMESTAMP(), server_default=sa.text(
            'CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('metric', sa.String(length=64), nullable=False),
        sa.Column('amount', sa.BigInteger(),
                  server_default=sa.text('0'), nullable=False),
        sa.Column('scope_id', sa.String(), nullable=True),
        sa.Column('request_id', sa.String(), nullable=True),
        sa.Column('endpoint', sa.String(), nullable=True),
        sa.Column('extra', sa.JSON(), nullable=True),
    )
    op.create_index('ix_quota_usage_ts', 'quota_usage', ['ts'], unique=False)
    op.create_index('ix_quota_usage_provider', 'quota_usage',
                    ['provider'], unique=False)
    op.create_index('ix_quota_usage_metric', 'quota_usage',
                    ['metric'], unique=False)
    op.create_index('ix_quota_usage_scope', 'quota_usage',
                    ['scope_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema: drop quota_usage indexes and table."""
    op.drop_index('ix_quota_usage_scope', table_name='quota_usage')
    op.drop_index('ix_quota_usage_metric', table_name='quota_usage')
    op.drop_index('ix_quota_usage_provider', table_name='quota_usage')
    op.drop_index('ix_quota_usage_ts', table_name='quota_usage')
    op.drop_table('quota_usage')
