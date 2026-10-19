"""add accepted_suggestion_id, dismissal_reason, reject_reason to ai_findings

Revision ID: a4f82e91c305
Revises: c213424f0fa3
Create Date: 2026-06-10 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4f82e91c305'
down_revision: Union[str, Sequence[str], None] = 'c213424f0fa3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 0019: persist which marketing suggestion compliance accepted (NULL = AI alternative chosen)
    op.execute(
        """
        ALTER TABLE ai_findings
          ADD COLUMN IF NOT EXISTS accepted_suggestion_id UUID
          REFERENCES finding_suggestions(id) ON DELETE SET NULL
        """
    )

    # 0020: free-text reason when a finding is dismissed
    op.execute(
        "ALTER TABLE ai_findings ADD COLUMN IF NOT EXISTS dismissal_reason TEXT"
    )

    # 0021: free-text reason when a finding is rejected
    op.execute(
        "ALTER TABLE ai_findings ADD COLUMN IF NOT EXISTS reject_reason TEXT"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ai_findings', 'reject_reason')
    op.drop_column('ai_findings', 'dismissal_reason')
    op.drop_column('ai_findings', 'accepted_suggestion_id')
