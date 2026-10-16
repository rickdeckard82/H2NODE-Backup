"""IP da UNM2000 (gerenciador) nas OLTs Fiberhome

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16 15:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('client', sa.Column('manager_ip', sa.String(length=45), nullable=True))


def downgrade() -> None:
    op.drop_column('client', 'manager_ip')
