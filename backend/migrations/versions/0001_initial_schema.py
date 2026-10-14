"""initial schema

Revision ID: 0001
Revises: 

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_log',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('target_type', sa.String(length=40), nullable=False),
    sa.Column('target_id', sa.String(length=36), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_at'), ['at'], unique=False)

    op.create_table('facilities',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('type', sa.String(length=80), nullable=False),
    sa.Column('district', sa.String(length=80), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=True),
    sa.Column('beds', sa.Integer(), nullable=True),
    sa.Column('hfr_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('facilities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_facilities_district'), ['district'], unique=False)

    op.create_table('otp_codes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('code_hash', sa.String(length=128), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('otp_codes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_otp_codes_email'), ['email'], unique=False)

    op.create_table('facility_services',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('facility_id', sa.String(length=36), nullable=False),
    sa.Column('service', sa.String(length=80), nullable=False),
    sa.Column('availability', sa.String(length=20), nullable=False),
    sa.Column('availability_note', sa.String(length=200), nullable=True),
    sa.Column('availability_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('learned_from_referral_id', sa.String(length=36), nullable=True),
    sa.CheckConstraint("availability IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')", name='ck_availability_valid'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('facility_id', 'service')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('facility_id', sa.String(length=36), nullable=True),
    sa.Column('district', sa.String(length=80), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role IN ('WORKER', 'FACILITY_STAFF', 'DOCTOR', 'COORDINATOR')", name='ck_role_valid'),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('idempotency_keys',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('response', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('patients',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('age', sa.Integer(), nullable=False),
    sa.Column('sex', sa.String(length=1), nullable=True),
    sa.Column('phone', sa.String(length=10), nullable=False),
    sa.Column('abha_number', sa.String(length=20), nullable=True),
    sa.Column('consent_recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("sex IN ('F', 'M', 'O')", name='ck_sex_valid'),
    sa.CheckConstraint('age >= 0 AND age <= 120', name='ck_age_range'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_patients_phone'), ['phone'], unique=False)

    op.create_table('encounters',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('patient_id', sa.String(length=36), nullable=False),
    sa.Column('created_by_id', sa.String(length=36), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('triage', sa.String(length=20), nullable=False),
    sa.Column('systolic', sa.Float(), nullable=True),
    sa.Column('diastolic', sa.Float(), nullable=True),
    sa.Column('pulse', sa.Float(), nullable=True),
    sa.Column('temperature_c', sa.Float(), nullable=True),
    sa.Column('spo2', sa.Float(), nullable=True),
    sa.Column('respiratory_rate', sa.Float(), nullable=True),
    sa.Column('glucose_mg_dl', sa.Float(), nullable=True),
    sa.Column('weight_kg', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("triage IN ('EMERGENCY', 'PRIORITY', 'ROUTINE')", name='ck_triage_valid'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('encounters', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_encounters_patient_id'), ['patient_id'], unique=False)

    op.create_table('medicines',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('encounter_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('dose', sa.String(length=60), nullable=True),
    sa.Column('frequency', sa.String(length=60), nullable=True),
    sa.Column('notes', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['encounter_id'], ['encounters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('referrals',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=12), nullable=False),
    sa.Column('patient_id', sa.String(length=36), nullable=False),
    sa.Column('encounter_id', sa.String(length=36), nullable=False),
    sa.Column('created_by_id', sa.String(length=36), nullable=False),
    sa.Column('destination_facility_id', sa.String(length=36), nullable=False),
    sa.Column('requested_service', sa.String(length=80), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('triage', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('rejection_reason', sa.String(length=40), nullable=True),
    sa.Column('follow_up_days', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('CREATED', 'ACCEPTED', 'REJECTED', 'ARRIVAL_RECORDED', 'CONSULTED', 'OUTCOME_RECORDED', 'FOLLOW_UP_DUE', 'OVERDUE', 'ESCALATED', 'CLOSED')", name='ck_status_valid'),
    sa.CheckConstraint("triage IN ('EMERGENCY', 'PRIORITY', 'ROUTINE')", name='ck_triage_valid'),
    sa.CheckConstraint('follow_up_days IS NULL OR follow_up_days BETWEEN 1 AND 365', name='ck_follow_up_days'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['destination_facility_id'], ['facilities.id'], ),
    sa.ForeignKeyConstraint(['encounter_id'], ['encounters.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('referrals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_referrals_code'), ['code'], unique=True)
        batch_op.create_index(batch_op.f('ix_referrals_created_by_id'), ['created_by_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_referrals_destination_facility_id'), ['destination_facility_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_referrals_patient_id'), ['patient_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_referrals_status'), ['status'], unique=False)

    op.create_table('follow_ups',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('referral_id', sa.String(length=36), nullable=False),
    sa.Column('assigned_to_id', sa.String(length=36), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('DUE', 'COMPLETED', 'MISSED', 'OVERDUE', 'ESCALATED')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['assigned_to_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['referral_id'], ['referrals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('follow_ups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_follow_ups_assigned_to_id'), ['assigned_to_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_follow_ups_referral_id'), ['referral_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('referral_id', sa.String(length=36), nullable=True),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('message', sa.String(length=300), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['referral_id'], ['referrals.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'referral_id', 'kind')
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)

    op.create_table('referral_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('referral_id', sa.String(length=36), nullable=False),
    sa.Column('from_status', sa.String(length=20), nullable=True),
    sa.Column('to_status', sa.String(length=20), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source IN ('ONLINE', 'OFFLINE_PASS', 'SYSTEM')", name='ck_source_valid'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['referral_id'], ['referrals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('referral_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_referral_events_referral_id'), ['referral_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('referral_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_referral_events_referral_id'))

    op.drop_table('referral_events')
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))

    op.drop_table('notifications')
    with op.batch_alter_table('follow_ups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_follow_ups_referral_id'))
        batch_op.drop_index(batch_op.f('ix_follow_ups_assigned_to_id'))

    op.drop_table('follow_ups')
    with op.batch_alter_table('referrals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_referrals_status'))
        batch_op.drop_index(batch_op.f('ix_referrals_patient_id'))
        batch_op.drop_index(batch_op.f('ix_referrals_destination_facility_id'))
        batch_op.drop_index(batch_op.f('ix_referrals_created_by_id'))
        batch_op.drop_index(batch_op.f('ix_referrals_code'))

    op.drop_table('referrals')
    op.drop_table('medicines')
    with op.batch_alter_table('encounters', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_encounters_patient_id'))

    op.drop_table('encounters')
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_patients_phone'))

    op.drop_table('patients')
    op.drop_table('idempotency_keys')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    op.drop_table('facility_services')
    with op.batch_alter_table('otp_codes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_otp_codes_email'))

    op.drop_table('otp_codes')
    with op.batch_alter_table('facilities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_facilities_district'))

    op.drop_table('facilities')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_at'))

    op.drop_table('audit_log')
