"""personal codes for every approved person

Revision ID: 0009
Revises: 0008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('code_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('pending_code', sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column('code_issued_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint('uq_users_code_hash', ['code_hash'])


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_constraint('uq_users_code_hash', type_='unique')
        batch_op.drop_column('code_issued_at')
        batch_op.drop_column('pending_code')
        batch_op.drop_column('code_hash')
