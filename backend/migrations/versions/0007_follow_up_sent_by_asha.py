"""follow-up checkup: the ASHA sends the patient, the hospital confirms

Revision ID: 0007
Revises: 0006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('follow_ups') as batch:
        batch.add_column(sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('follow_ups') as batch:
        batch.drop_column('sent_at')
