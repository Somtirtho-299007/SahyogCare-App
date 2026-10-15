"""invite codes

Revision ID: 0004
Revises: 0003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('invite_codes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=24), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('district', sa.String(length=80), nullable=False),
    sa.Column('facility_id', sa.String(length=36), nullable=True),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.Column('max_uses', sa.Integer(), nullable=True),
    sa.Column('uses', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role IN ('WORKER', 'FACILITY_STAFF', 'DOCTOR', 'COORDINATOR')", name='ck_role_valid'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('invite_codes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_invite_codes_code'), ['code'], unique=True)
        batch_op.create_index(batch_op.f('ix_invite_codes_district'), ['district'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('invite_codes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invite_codes_district'))
        batch_op.drop_index(batch_op.f('ix_invite_codes_code'))

    op.drop_table('invite_codes')
