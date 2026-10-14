"""health record, care chart, photos, patient emergency booking, deceased, phone login

Revision ID: 0008
Revises: 0007

"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES_OLD = ["CREATED", "ACCEPTED", "REJECTED", "ARRIVAL_RECORDED", "CONSULTED", "OUTCOME_RECORDED",
                "FOLLOW_UP_DUE", "OVERDUE", "ESCALATED", "CLOSED", "REROUTED"]
STATUSES_NEW = STATUSES_OLD + ["DECEASED"]
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _in(column: str, values: list[str]) -> str:
    return f"{column} IN (%s)" % ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table('photos',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_type', sa.String(length=20), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=True),
    sa.Column('content_type', sa.String(length=20), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('uploaded_by_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('photos') as batch_op:
        batch_op.create_index(batch_op.f('ix_photos_owner_id'), ['owner_id'], unique=False)

    op.create_table('conditions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('patient_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('noted_on', sa.Date(), nullable=True),
    sa.Column('created_by_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(_in('status', ['ACTIVE', 'CHRONIC', 'RESOLVED']), name='ck_status_valid'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('conditions') as batch_op:
        batch_op.create_index(batch_op.f('ix_conditions_patient_id'), ['patient_id'], unique=False)

    op.create_table('condition_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('condition_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('by_id', sa.String(length=36), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(_in('status', ['ACTIVE', 'CHRONIC', 'RESOLVED']), name='ck_status_valid'),
    sa.ForeignKeyConstraint(['by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['condition_id'], ['conditions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('condition_events') as batch_op:
        batch_op.create_index(batch_op.f('ix_condition_events_condition_id'), ['condition_id'], unique=False)

    op.create_table('prescriptions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('patient_id', sa.String(length=36), nullable=False),
    sa.Column('referral_id', sa.String(length=36), nullable=True),
    sa.Column('doctor_name', sa.String(length=120), nullable=True),
    sa.Column('facility_name', sa.String(length=200), nullable=True),
    sa.Column('prescribed_on', sa.Date(), nullable=True),
    sa.Column('diagnosis', sa.String(length=300), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('photo_id', sa.String(length=36), nullable=True),
    sa.Column('recorded_by_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.ForeignKeyConstraint(['recorded_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['referral_id'], ['referrals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('prescriptions') as batch_op:
        batch_op.create_index(batch_op.f('ix_prescriptions_patient_id'), ['patient_id'], unique=False)

    op.create_table('care_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('patient_id', sa.String(length=36), nullable=False),
    sa.Column('prescription_id', sa.String(length=36), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('dose', sa.String(length=60), nullable=True),
    sa.Column('quantity', sa.String(length=60), nullable=True),
    sa.Column('timings', sa.JSON(), nullable=False),
    sa.Column('food', sa.String(length=10), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('duration_days', sa.Integer(), nullable=True),
    sa.Column('instructions', sa.String(length=300), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_reason', sa.String(length=200), nullable=True),
    sa.Column('created_by_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(_in('kind', ['MEDICINE', 'PRACTICE']), name='ck_kind_valid'),
    sa.CheckConstraint(_in('category', ['GENERAL', 'PREGNANCY', 'AFTER_SURGERY', 'CHRONIC', 'CHILD', 'OTHER']),
                       name='ck_category_valid'),
    sa.CheckConstraint(_in('status', ['ACTIVE', 'COMPLETED', 'STOPPED']), name='ck_status_valid'),
    sa.CheckConstraint(_in('food', ['BEFORE', 'AFTER', 'WITH', 'ANY']), name='ck_food_valid'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.ForeignKeyConstraint(['prescription_id'], ['prescriptions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('care_items') as batch_op:
        batch_op.create_index(batch_op.f('ix_care_items_patient_id'), ['patient_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_care_items_status'), ['status'], unique=False)

    op.create_table('reminder_log',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('patient_id', sa.String(length=36), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('slot', sa.String(length=20), nullable=False),
    sa.Column('channel', sa.String(length=10), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('patient_id', 'day', 'slot')
    )
    with op.batch_alter_table('reminder_log') as batch_op:
        batch_op.create_index(batch_op.f('ix_reminder_log_patient_id'), ['patient_id'], unique=False)

    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('email', existing_type=sa.String(length=254), nullable=True)
        batch_op.add_column(sa.Column('phone', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('photo_id', sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_phone'), ['phone'], unique=True)

    with op.batch_alter_table('access_requests') as batch_op:
        batch_op.add_column(sa.Column('photo_id', sa.String(length=36), nullable=True))

    with op.batch_alter_table('patients') as batch_op:
        batch_op.add_column(sa.Column('health_id', sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column('email', sa.String(length=254), nullable=True))
        batch_op.add_column(sa.Column('language', sa.String(length=5), server_default='bn', nullable=False))
        batch_op.add_column(sa.Column('address', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('latitude', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('longitude', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('photo_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('reminders', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('deceased_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('death_cause', sa.String(length=300), nullable=True))
        batch_op.create_index(batch_op.f('ix_patients_health_id'), ['health_id'], unique=True)

    # Every existing patient gets a Health ID for signing in.
    conn = op.get_bind()
    used: set[str] = set()
    for (pid,) in conn.execute(sa.text("SELECT id FROM patients")).fetchall():
        hid = None
        while hid is None or hid in used:
            hid = "HID-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
        used.add(hid)
        conn.execute(sa.text("UPDATE patients SET health_id = :h WHERE id = :i"), {"h": hid, "i": pid})

    with op.batch_alter_table('encounters') as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=20), server_default='REFERRAL', nullable=False))
        batch_op.add_column(sa.Column('referral_id', sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f('ix_encounters_referral_id'), ['referral_id'], unique=False)

    with op.batch_alter_table('referrals') as batch_op:
        batch_op.add_column(sa.Column('origin', sa.String(length=20), server_default='ASHA', nullable=False))
        # Referrals can now end as DECEASED.
        batch_op.drop_constraint('ck_status_valid', type_='check')
        batch_op.create_check_constraint('ck_status_valid', _in('status', STATUSES_NEW))


def downgrade() -> None:
    with op.batch_alter_table('referrals') as batch_op:
        batch_op.drop_constraint('ck_status_valid', type_='check')
        batch_op.create_check_constraint('ck_status_valid', _in('status', STATUSES_OLD))
        batch_op.drop_column('origin')

    with op.batch_alter_table('encounters') as batch_op:
        batch_op.drop_index(batch_op.f('ix_encounters_referral_id'))
        batch_op.drop_column('referral_id')
        batch_op.drop_column('kind')

    with op.batch_alter_table('patients') as batch_op:
        batch_op.drop_index(batch_op.f('ix_patients_health_id'))
        for col in ('death_cause', 'deceased_at', 'reminders', 'photo_id', 'longitude', 'latitude', 'address',
                    'language', 'email', 'health_id'):
            batch_op.drop_column(col)

    with op.batch_alter_table('access_requests') as batch_op:
        batch_op.drop_column('photo_id')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_phone'))
        batch_op.drop_column('photo_id')
        batch_op.drop_column('phone')
        batch_op.alter_column('email', existing_type=sa.String(length=254), nullable=False)

    for table in ('reminder_log', 'care_items', 'prescriptions', 'condition_events', 'conditions', 'photos'):
        op.drop_table(table)
