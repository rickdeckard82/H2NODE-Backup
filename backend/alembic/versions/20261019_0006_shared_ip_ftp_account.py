"""IP de origem compartilhado: conta FTP presa ao cadastro

O mesmo IP pode ter vários cadastros (ex.: serviços no mesmo servidor enviando por FTP,
ou um MikroTik coletado por SSH): o FTP distingue pela conta usada no login.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 23:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint('uq_client_mgmt_ip', 'client', type_='unique')
    op.create_index(op.f('ix_client_mgmt_ip'), 'client', ['mgmt_ip'], unique=False)
    op.add_column('client', sa.Column('ftp_account_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_client_ftp_account_id', 'client', 'ftp_account', ['ftp_account_id'], ['id'],
                          ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_client_ftp_account_id', 'client', type_='foreignkey')
    op.drop_column('client', 'ftp_account_id')
    op.drop_index(op.f('ix_client_mgmt_ip'), table_name='client')
    op.create_unique_constraint('uq_client_mgmt_ip', 'client', ['mgmt_ip'])
