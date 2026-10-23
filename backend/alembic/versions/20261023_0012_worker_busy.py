"""Tarefa atual do worker (sinal de vida durante tarefas longas)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-23 15:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('worker_status', sa.Column('busy_with', sa.String(length=255), nullable=True))
    op.add_column('worker_status', sa.Column('busy_since', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('worker_status', 'busy_since')
    op.drop_column('worker_status', 'busy_with')
