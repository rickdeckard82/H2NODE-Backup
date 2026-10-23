"""Dispositivos lembrados no 2FA

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22 23:30:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'app_trusted_device',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('system_user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(['system_user_id'], ['app_system_user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_app_trusted_device_system_user_id'), 'app_trusted_device', ['system_user_id'],
                    unique=False)
    op.create_index(op.f('ix_app_trusted_device_token_hash'), 'app_trusted_device', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_app_trusted_device_token_hash'), table_name='app_trusted_device')
    op.drop_index(op.f('ix_app_trusted_device_system_user_id'), table_name='app_trusted_device')
    op.drop_table('app_trusted_device')
