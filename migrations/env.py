from logging.config import fileConfig
import os
import sys
import pathlib
from sqlalchemy import pool, create_engine
from alembic import context

# Ensure project root on path so we can import `app.*`
ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: F401,E402  (ensure models are imported for metadata)
from app.settings import Settings  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate'
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def _get_url() -> str:
    """Resolve DB URL from environment/settings with a dev fallback.

    Alembic does not load our FastAPI application, so we recreate settings here.
    Falls back to a local sqlite file to allow migration generation even if
    DATABASE_URL isn't configured yet.
    """
    settings = Settings()
    url = settings.DATABASE_URL
    if not url:
        # persistent sqlite file (relative to project root) for local dev
        return "sqlite:///./dev.db"
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    # Prefer dynamic resolution over static alembic.ini value
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    url = _get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
