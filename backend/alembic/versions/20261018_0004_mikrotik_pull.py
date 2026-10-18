"""MikroTik: credenciais de acesso SSH e campos de coleta no equipamento

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18 10:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('device_credential',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_enc', sa.String(length=512), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_device_credential_name'), 'device_credential', ['name'], unique=True)
    op.add_column('client', sa.Column('pull_credential_id', sa.Integer(), nullable=True))
    op.add_column('client', sa.Column('pull_port', sa.Integer(), nullable=True))
    op.add_column('client', sa.Column('pull_host_key', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('pull_next_at', sa.DateTime(), nullable=True))
    op.add_column('client', sa.Column('pull_last_at', sa.DateTime(), nullable=True))
    op.add_column('client', sa.Column('pull_error', sa.Text(), nullable=True))
    op.create_index(op.f('ix_client_pull_credential_id'), 'client', ['pull_credential_id'], unique=False)
    op.create_foreign_key('fk_client_pull_credential', 'client', 'device_credential',
                          ['pull_credential_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    op.drop_constraint('fk_client_pull_credential', 'client', type_='foreignkey')
    op.drop_index(op.f('ix_client_pull_credential_id'), table_name='client')
    op.drop_column('client', 'pull_error')
    op.drop_column('client', 'pull_last_at')
    op.drop_column('client', 'pull_next_at')
    op.drop_column('client', 'pull_host_key')
    op.drop_column('client', 'pull_port')
    op.drop_column('client', 'pull_credential_id')
    op.drop_index(op.f('ix_device_credential_name'), table_name='device_credential')
    op.drop_table('device_credential')
