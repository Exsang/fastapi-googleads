"""add embeddings table with pgvector

Revision ID: 0e1a2b3c4d55
Revises: e98d950c5b31
Create Date: 2025-11-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
try:
    from pgvector.sqlalchemy import Vector  # type: ignore
except Exception:  # pragma: no cover
    Vector = None  # type: ignore

revision = '0e1a2b3c4d55'
down_revision = 'e98d950c5b31'
branch_labels = None
depends_on = None


def _is_sqlite() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == 'sqlite'


def upgrade() -> None:
    # Enable pgvector extension if Postgres
    if not _is_sqlite():
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:
            pass

    # Create table (dialect-aware for embedding column)
    if _is_sqlite():
        op.create_table(
            'embedding',
            sa.Column('id', sa.BigInteger(),
                      primary_key=True, autoincrement=True),
            sa.Column('provider', sa.String(64), nullable=False),
            sa.Column('model', sa.String(128), nullable=False),
            sa.Column('entity_type', sa.String(32), nullable=False),
            sa.Column('entity_id', sa.String(128), nullable=True),
            sa.Column('scope_id', sa.String(64), nullable=True),
            sa.Column('title', sa.String(512), nullable=True),
            sa.Column('text', sa.Text(), nullable=False),
            sa.Column('text_hash', sa.String(64), nullable=False),
            sa.Column('chunk_index', sa.Integer(), nullable=True),
            sa.Column('meta', sa.JSON(), nullable=True),
            sa.Column('embedding', sa.JSON(), nullable=True),
            sa.Column('dim', sa.Integer(), nullable=False,
                      server_default='1536'),
            sa.Column('ts', sa.TIMESTAMP(),
                      server_default=sa.func.now(), nullable=False),
        )
        # Basic indexes for lookup
        for col in ['provider', 'model', 'entity_type', 'entity_id', 'scope_id', 'text_hash', 'ts']:
            op.create_index(f'ix_embedding_{col}', 'embedding', [
                            col], unique=False)
    else:
        op.create_table(
            'embedding',
            sa.Column('id', sa.BigInteger(),
                      primary_key=True, autoincrement=True),
            sa.Column('provider', sa.String(64), nullable=False),
            sa.Column('model', sa.String(128), nullable=False),
            sa.Column('entity_type', sa.String(32), nullable=False),
            sa.Column('entity_id', sa.String(128), nullable=True),
            sa.Column('scope_id', sa.String(64), nullable=True),
            sa.Column('title', sa.String(512), nullable=True),
            sa.Column('text', sa.Text(), nullable=False),
            sa.Column('text_hash', sa.String(64), nullable=False),
            sa.Column('chunk_index', sa.Integer(), nullable=True),
            sa.Column('meta', sa.JSON(), nullable=True),
            sa.Column('embedding', Vector(1536)),  # type: ignore[arg-type]
            sa.Column('dim', sa.Integer(), nullable=False,
                      server_default='1536'),
            sa.Column('ts', sa.TIMESTAMP(),
                      server_default=sa.func.now(), nullable=False),
        )
        # ANN and btree indexes
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_embedding_vector_ivfflat ON embedding USING ivfflat (embedding vector_cosine_ops)")
        for col in ['provider', 'model', 'entity_type', 'entity_id', 'scope_id', 'text_hash', 'ts']:
            op.execute(
                f"CREATE INDEX IF NOT EXISTS ix_embedding_{col} ON embedding ({col})")

    # ANN index only if Postgres
    if not _is_sqlite():
        # ivfflat index (requires ANALYZE after population for performance tuning)
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_embedding_vector_ivfflat ON embedding USING ivfflat (embedding vector_cosine_ops)")

    # (indexes created above per dialect)


def downgrade() -> None:
    op.drop_table('embedding')
