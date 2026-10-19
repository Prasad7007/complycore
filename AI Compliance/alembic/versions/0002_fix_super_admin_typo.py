"""fix super admin typo

Revision ID: c2b6e3c4d5f1
Revises: b1a5e2c3d4f0
Create Date: 2026-05-19

"""
from alembic import op

# revision identifiers used by Alembic
revision = "c2b6e3c4d5f1"
down_revision = "b1a5e2c3d4f0"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Insert 'Super Admin' into catalog
    op.execute("INSERT INTO department_catalog (name) VALUES ('Super Admin') ON CONFLICT (name) DO NOTHING;")
    
    # 2. Update user profiles to 'Super Admin'
    op.execute("UPDATE user_profiles SET department = 'Super Admin' WHERE department IN ('Supre Admin', 'super_admin');")
    
    # 3. Delete 'Supre Admin' from catalog
    op.execute("DELETE FROM department_catalog WHERE name = 'Supre Admin';")

def downgrade() -> None:
    pass
