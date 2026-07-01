"""baseline

Revision ID: 0002_baseline
Revises: 0001_add_orderaudit
Create Date: 2026-07-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002_baseline'
down_revision = '0001_add_orderaudit'
branch_labels = None
depends_on = None


def upgrade():
    # Baseline migration - schema already matches models.
    pass


def downgrade():
    pass
