"""Servidor de firmwares (FTP/TFTP só leitura)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22 10:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'firmware_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('ftp_username', sa.String(length=64), nullable=True),
        sa.Column('ftp_password_hash', sa.String(length=255), nullable=True),
        sa.Column('allowed_networks', sa.Text(), nullable=False),
        sa.Column('include_devices', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('firmware_settings')
