"""hospital address source and active flag

Revision ID: 0005
Revises: 0004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('facilities', schema=None) as batch_op:
        batch_op.add_column(sa.Column('address', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('pincode', sa.String(length=6), nullable=True))
        batch_op.add_column(sa.Column('source', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('facilities', schema=None) as batch_op:
        batch_op.drop_column('active')
        batch_op.drop_column('source')
        batch_op.drop_column('pincode')
        batch_op.drop_column('address')

