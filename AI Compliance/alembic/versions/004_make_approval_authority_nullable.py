"""make approval_authority nullable

Revision ID: c213424f0fa3
Revises: d3e7f4a5b6c2
Create Date: 2026-06-08 14:23:02.818109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c213424f0fa3'
down_revision: Union[str, Sequence[str], None] = 'd3e7f4a5b6c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('compliance_reports', 'approval_authority', nullable=True)
    op.drop_constraint('compliance_reports_approval_authority_fkey', 'compliance_reports', type_='foreignkey')
    op.create_foreign_key(
        'compliance_reports_approval_authority_fkey',
        'compliance_reports', 'user_profiles',
        ['approval_authority'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('compliance_reports_approval_authority_fkey', 'compliance_reports', type_='foreignkey')
    op.create_foreign_key(
        'compliance_reports_approval_authority_fkey',
        'compliance_reports', 'user_profiles',
        ['approval_authority'], ['id']
    )
    op.alter_column('compliance_reports', 'approval_authority', nullable=False)
