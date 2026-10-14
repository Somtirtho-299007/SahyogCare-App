"""patients can make their own account

Revision ID: 0010
Revises: 0009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('patients') as batch_op:
        batch_op.add_column(sa.Column('self_registered', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('patients') as batch_op:
        batch_op.drop_column('self_registered')
