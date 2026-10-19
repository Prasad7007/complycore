"""add compliance report code sequence

Revision ID: b5e9f1a2d306
Revises: a4f82e91c305
Create Date: 2026-06-23 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5e9f1a2d306'
down_revision: Union[str, Sequence[str], None] = 'a4f82e91c305'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE SEQUENCE IF NOT EXISTS compliance_report_code_seq;
        
        DO $$
        DECLARE
            max_val INTEGER;
        BEGIN
            SELECT COALESCE(MAX(CAST(SUBSTRING(report_code FROM 5) AS INTEGER)), 0)
            INTO max_val
            FROM compliance_reports
            WHERE report_code LIKE 'RPT-%' AND report_code ~ '^RPT-\\d+$';
            
            PERFORM setval('compliance_report_code_seq', max_val + 1, false);
        END $$;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP SEQUENCE IF EXISTS compliance_report_code_seq;")
