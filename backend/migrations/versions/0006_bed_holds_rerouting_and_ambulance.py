"""bed holds rerouting and ambulance

Revision ID: 0006
Revises: 0005

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES_OLD = ["CREATED", "ACCEPTED", "REJECTED", "ARRIVAL_RECORDED", "CONSULTED", "OUTCOME_RECORDED",
                "FOLLOW_UP_DUE", "OVERDUE", "ESCALATED", "CLOSED"]
STATUSES_NEW = STATUSES_OLD + ["REROUTED"]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ambulance_trips',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('referral_id', sa.String(length=36), nullable=False),
    sa.Column('facility_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('pickup_note', sa.String(length=300), nullable=False),
    sa.Column('requested_by_id', sa.String(length=36), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('eta_minutes', sa.Integer(), nullable=True),
    sa.Column('vehicle_number', sa.String(length=20), nullable=True),
    sa.Column('driver_phone', sa.String(length=10), nullable=True),
    sa.Column('picked_up_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_reason', sa.String(length=200), nullable=True),
    sa.CheckConstraint("status IN ('REQUESTED', 'DISPATCHED', 'PICKED_UP', 'COMPLETED', 'CANCELLED')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
    sa.ForeignKeyConstraint(['referral_id'], ['referrals.id'], ),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ambulance_trips', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ambulance_trips_facility_id'), ['facility_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ambulance_trips_referral_id'), ['referral_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ambulance_trips_status'), ['status'], unique=False)

    op.create_table('bed_holds',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('referral_id', sa.String(length=36), nullable=False),
    sa.Column('facility_id', sa.String(length=36), nullable=False),
    sa.Column('ward', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('held_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('release_reason', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('HELD', 'OCCUPIED', 'RELEASED', 'EXPIRED')", name='ck_status_valid'),
    sa.CheckConstraint("ward IN ('GENERAL', 'EMERGENCY', 'MATERNITY', 'PAEDIATRIC', 'ICU')", name='ck_ward_valid'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
    sa.ForeignKeyConstraint(['referral_id'], ['referrals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('referral_id')
    )
    with op.batch_alter_table('bed_holds', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bed_holds_facility_id'), ['facility_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bed_holds_status'), ['status'], unique=False)

    with op.batch_alter_table('referrals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rerouted_from_id', sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f('ix_referrals_rerouted_from_id'), ['rerouted_from_id'], unique=False)
        batch_op.create_foreign_key('fk_referrals_rerouted_from_id', 'referrals', ['rerouted_from_id'], ['id'])
        # Referrals can now end as REROUTED.
        batch_op.drop_constraint('ck_status_valid', type_='check')
        batch_op.create_check_constraint('ck_status_valid', "status IN (%s)" % ", ".join(f"'{x}'" for x in STATUSES_NEW))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('referrals', schema=None) as batch_op:
        # WARNING: constraint name is None; this directive will fail as
        # rendered.  Add a name, or use a naming convention; see
        # https://alembic.sqlalchemy.org/en/latest/naming.html
        batch_op.drop_constraint('ck_status_valid', type_='check')
        batch_op.create_check_constraint('ck_status_valid', "status IN (%s)" % ", ".join(f"'{x}'" for x in STATUSES_OLD))
        batch_op.drop_constraint('fk_referrals_rerouted_from_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_referrals_rerouted_from_id'))
        batch_op.drop_column('rerouted_from_id')

    with op.batch_alter_table('bed_holds', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bed_holds_status'))
        batch_op.drop_index(batch_op.f('ix_bed_holds_facility_id'))

    op.drop_table('bed_holds')
    with op.batch_alter_table('ambulance_trips', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ambulance_trips_status'))
        batch_op.drop_index(batch_op.f('ix_ambulance_trips_referral_id'))
        batch_op.drop_index(batch_op.f('ix_ambulance_trips_facility_id'))

    op.drop_table('ambulance_trips')
