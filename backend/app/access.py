"""Who may see which records (the "scope" half of every permission check).

Records outside a user's scope are reported as NOT_FOUND, never FORBIDDEN,
so the API does not reveal that they exist.
"""

from sqlalchemy import exists, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.errors import ApiError
from app.models import Patient, Referral, User
from app.rules import Role

NOT_FOUND = "Not found."


def referral_scope(user: User) -> ColumnElement[bool]:
    """SQL condition: referrals this user may see."""
    if user.role == Role.WORKER:
        return Referral.created_by_id == user.id
    if user.role in (Role.FACILITY_STAFF, Role.DOCTOR):
        return Referral.destination_facility_id == user.facility_id
    # COORDINATOR: referrals created by workers in their district.
    return Referral.created_by_id.in_(select(User.id).where(User.district == user.district))


def patient_scope(user: User) -> ColumnElement[bool]:
    """SQL condition: patients this user may see."""
    if user.role == Role.WORKER:
        return Patient.created_by_id == user.id
    if user.role in (Role.FACILITY_STAFF, Role.DOCTOR):
        return exists().where(
            Referral.patient_id == Patient.id, Referral.destination_facility_id == user.facility_id
        )
    return Patient.created_by_id.in_(select(User.id).where(User.district == user.district))


def get_referral_for(db: Session, user: User, referral_id: str) -> Referral:
    referral = db.scalar(select(Referral).where(Referral.id == referral_id, referral_scope(user)))
    if referral is None:
        raise ApiError(404, "NOT_FOUND", NOT_FOUND)
    return referral


def get_patient_for(db: Session, user: User, patient_id: str) -> Patient:
    patient = db.scalar(select(Patient).where(Patient.id == patient_id, patient_scope(user)))
    if patient is None:
        raise ApiError(404, "NOT_FOUND", NOT_FOUND)
    return patient
