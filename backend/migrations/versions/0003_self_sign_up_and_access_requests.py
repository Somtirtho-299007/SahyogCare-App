"""self sign-up and access requests

Revision ID: 0003
Revises: 0002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('access_requests',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('requested_role', sa.String(length=20), nullable=False),
    sa.Column('facility_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('decided_by_id', sa.String(length=36), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("requested_role IN ('WORKER', 'FACILITY_STAFF', 'DOCTOR', 'COORDINATOR')", name='ck_requested_role_valid'),
    sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('access_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_access_requests_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_access_requests_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approved', sa.Boolean(), server_default=sa.true(), nullable=False))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('approved')

    with op.batch_alter_table('access_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_access_requests_user_id'))
        batch_op.drop_index(batch_op.f('ix_access_requests_status'))

    op.drop_table('access_requests')
