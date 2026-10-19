"""add audit event code sequence

Revision ID: c7f3a812e407
Revises: b5e9f1a2d306
Create Date: 2026-08-06 04:42:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f3a812e407'
down_revision: Union[str, Sequence[str], None] = 'b5e9f1a2d306'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create audit_event_code_seq and seed it from the current max value."""
    op.execute(
        """
        CREATE SEQUENCE IF NOT EXISTS audit_event_code_seq;

        DO $$
        DECLARE
            max_val INTEGER;
        BEGIN
            SELECT COALESCE(MAX(CAST(REPLACE(event_code, 'AE-', '') AS INTEGER)), 0)
            INTO max_val
            FROM audit_events
            WHERE event_code LIKE 'AE-%' AND event_code ~ '^AE-[0-9]+$';

            PERFORM setval('audit_event_code_seq', max_val + 1, false);
        END $$;
        """
    )


def downgrade() -> None:
    """Drop the sequence (event_code column retains existing values)."""
    op.execute("DROP SEQUENCE IF EXISTS audit_event_code_seq;")
