"""Baseline: full schema + migrations 0001-0016.

Revision ID: b1a5e2c3d4f0
Revises:
Create Date: 2026-05-18

NOTE FOR EXISTING DATABASES (dev / UAT):
  All 16 migrations are already applied. Do NOT run upgrade.
  Instead, mark this revision as applied without running SQL:

      cd "AI Compliance"
      alembic stamp head

  That writes the revision ID to the alembic_version table and
  Alembic will treat the DB as up-to-date.

NOTE FOR FRESH DATABASES (future prod):
  alembic upgrade head
  This will run schema.sql then each migration in order.
"""

from pathlib import Path
from alembic import op

# revision identifiers used by Alembic
revision = "b1a5e2c3d4f0"
down_revision = None
branch_labels = None
depends_on = None

# Root of the "AI Compliance" folder (one level up from alembic/versions/)
_BASE = Path(__file__).resolve().parent.parent.parent


def _run_sql_file(path: Path) -> None:
    sql = path.read_text(encoding="utf-8").strip()
    if sql:
        op.execute(sql)


def upgrade() -> None:
    """Apply full schema then all 16 incremental migrations."""
    _run_sql_file(_BASE / "schema.sql")

    migration_dir = _BASE / "migrations"
    for filename in sorted(migration_dir.glob("*.sql")):
        _run_sql_file(filename)

    # Recreate the alembic_version table because schema.sql's DROP SCHEMA CASCADE dropped it!
    op.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY);")


def downgrade() -> None:
    """No downgrade from baseline — this represents the initial schema."""
    raise NotImplementedError(
        "Downgrade from baseline is not supported. "
        "Restore from a database backup if needed."
    )
