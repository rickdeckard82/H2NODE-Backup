"""Fabricante dos firmwares

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23 08:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('firmware_note', sa.Column('vendor', sa.String(length=16), nullable=True))
    op.alter_column('firmware_note', 'comment', existing_type=sa.String(length=200), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM firmware_note WHERE comment IS NULL")
    op.alter_column('firmware_note', 'comment', existing_type=sa.String(length=200), nullable=False)
    op.drop_column('firmware_note', 'vendor')
