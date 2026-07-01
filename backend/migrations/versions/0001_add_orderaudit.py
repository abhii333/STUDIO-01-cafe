"""add orderaudit table

Revision ID: 0001_add_orderaudit
Revises: 
Create Date: 2026-07-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_add_orderaudit'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'order_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('meta', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('order_audit')
