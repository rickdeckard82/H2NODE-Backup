"""Token de envio por HTTPS (cliente Windows)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 18:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('client', sa.Column('upload_token_hash', sa.String(length=64), nullable=True))
    op.add_column('client', sa.Column('upload_token_hint', sa.String(length=16), nullable=True))
    op.create_unique_constraint('uq_client_upload_token_hash', 'client', ['upload_token_hash'])


def downgrade() -> None:
    op.drop_constraint('uq_client_upload_token_hash', 'client', type_='unique')
    op.drop_column('client', 'upload_token_hint')
    op.drop_column('client', 'upload_token_hash')
