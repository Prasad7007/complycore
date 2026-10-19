"""remove profile_handler (Social Media Handler) role only

Revision ID: d3e7f4a5b6c2
Revises: c2b6e3c4d5f1
Create Date: 2026-05-20

Deletes roles.name = profile_handler. Cascades user_roles and role_permissions
for that role only. Does not change other roles, permissions, or org memberships.
"""
from pathlib import Path

from alembic import op

revision = "d3e7f4a5b6c2"
down_revision = "c2b6e3c4d5f1"
branch_labels = None
depends_on = None

_BASE = Path(__file__).resolve().parent.parent.parent


def upgrade() -> None:
    sql = (_BASE / "migrations" / "0018_remove_profile_handler_role.sql").read_text(encoding="utf-8").strip()
    if sql:
        op.execute(sql)


def downgrade() -> None:
    # Re-create role via seed_db / manual ops if rollback is ever needed.
    pass
