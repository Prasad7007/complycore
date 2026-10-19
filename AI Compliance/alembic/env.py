"""
Alembic env.py — reads DATABASE_URL from .env / .env.docker / environment.

Usage:
  alembic upgrade head      # apply pending migrations
  alembic stamp head        # mark existing DB as up-to-date (no SQL run)
  alembic current           # show current revision
  alembic history           # list all revisions
  alembic revision -m "add_column_foo"  # create a new revision
"""

import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool
from alembic import context

# ── Alembic config object ────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None  # no SQLAlchemy models; we write raw SQL in revisions


# ── Resolve DATABASE_URL ─────────────────────────────────────────
def _get_db_url() -> str:
    """
    Load DATABASE_URL from the environment or from .env / .env.docker files.
    Strips +asyncpg since Alembic uses psycopg2 (sync driver).
    """
    url = os.environ.get("DATABASE_URL", "")

    if not url:
        here = Path(__file__).resolve().parent.parent  # AI Compliance/
        for candidate in [here / ".env", here / ".env.docker"]:
            if candidate.exists():
                with open(candidate) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("DATABASE_URL=") and not line.startswith("#"):
                            url = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            if url:
                break

    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. "
            "Export it in your shell or add it to AI Compliance/.env"
        )

    # Swap asyncpg driver for psycopg2 (Alembic needs sync driver)
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("+asyncpg", "")

    # When running on host machine (not inside Docker), replace Docker hostname
    url = url.replace("host.docker.internal", "localhost")

    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    url = _get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live DB connection."""
    url = _get_db_url()
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
