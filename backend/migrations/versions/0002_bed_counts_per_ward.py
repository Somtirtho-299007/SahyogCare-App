"""bed counts per ward

Revision ID: 0002
Revises: 0001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('bed_wards',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('facility_id', sa.String(length=36), nullable=False),
    sa.Column('ward', sa.String(length=20), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('occupied', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by_id', sa.String(length=36), nullable=True),
    sa.CheckConstraint("ward IN ('GENERAL', 'EMERGENCY', 'MATERNITY', 'PAEDIATRIC', 'ICU')", name='ck_ward_valid'),
    sa.CheckConstraint('total >= 0 AND occupied >= 0 AND occupied <= total', name='ck_bed_counts'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('facility_id', 'ward')
    )
    with op.batch_alter_table('bed_wards', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bed_wards_facility_id'), ['facility_id'], unique=False)

    with op.batch_alter_table('facilities', schema=None) as batch_op:
        batch_op.add_column(sa.Column('latitude', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('longitude', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('has_ambulance', sa.Boolean(), nullable=False, server_default=sa.false()))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('facilities', schema=None) as batch_op:
        batch_op.drop_column('has_ambulance')
        batch_op.drop_column('longitude')
        batch_op.drop_column('latitude')

    with op.batch_alter_table('bed_wards', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bed_wards_facility_id'))

    op.drop_table('bed_wards')
