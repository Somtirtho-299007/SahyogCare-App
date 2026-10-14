"""For patients: referral status without an account, and their own health record and
night emergency booking after signing in with the Health ID their ASHA gives them
(plus the last 4 digits of their phone). See docs/WORKFLOW.md, "Patient lookup"."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app import ambulance
from app.models import Facility, Patient, Referral
from app.config import settings
from app.ratelimit import RateLimiter
from app.rules import (
    EMERGENCY_GUIDE,
    NATIONAL_AMBULANCE_NUMBER,
    PATIENT_CHECKLIST,
    PATIENT_LOGINS_PER_MINUTE,
    PUBLIC_LOOKUPS_PER_MINUTE,
)
from app.schemas import (
    EmergencyIn,
    EmergencyOut,
    PatientLoginIn,
    PatientRecordOut,
    PatientTokenOut,
    PublicAmbulance,
    PublicLookupIn,
    PublicLookupOut,
    PublicStep,
)
from app.security import current_patient, patient_token_for
from app.workflow import commit
from app.timeutil import as_utc
from app.workflow import rerouted_to

router = APIRouter(prefix="/public", tags=["public"])
lookup_limiter = RateLimiter(PUBLIC_LOOKUPS_PER_MINUTE)
patient_login_limiter = RateLimiter(PATIENT_LOGINS_PER_MINUTE)


@router.post("/referral-status", response_model=PublicLookupOut)
def referral_status(body: PublicLookupIn, request: Request, db: Session = Depends(get_db)) -> PublicLookupOut:
    lookup_limiter.check(request.client.host if request.client else "unknown")

    referral = db.scalar(select(Referral).where(Referral.code == body.code))
    patient = db.get(Patient, referral.patient_id) if referral else None
    # Same answer for a wrong code and a wrong phone, so neither can be guessed separately.
    if patient is None or not patient.phone.endswith(body.phone_last4):
        raise ApiError(404, "NOT_FOUND", "No referral matches this code and phone number.")

    facility = db.get(Facility, referral.destination_facility_id)
    # Follow the chain to the referral that is current now, so an old code still finds the patient.
    latest = referral
    while (nxt := rerouted_to(db, latest)) is not None:
        latest = nxt
    moved = latest if latest.id != referral.id else None
    trip = ambulance.latest_trip(db, latest)
    return PublicLookupOut(
        code=referral.code,
        status=referral.status,
        facility_name=facility.name,
        timeline=[PublicStep(status=e.to_status, at=as_utc(e.at)) for e in referral.events],
        checklist=PATIENT_CHECKLIST,
        rerouted_to_code=moved.code if moved else None,
        rerouted_to_facility=db.get(Facility, moved.destination_facility_id).name if moved else None,
        ambulance=PublicAmbulance(status=trip.status, expected_at=ambulance.expected_at(trip),
                                  vehicle_number=trip.vehicle_number, driver_phone=trip.driver_phone)
        if trip else None,
        emergency_number=NATIONAL_AMBULANCE_NUMBER,
    )


@router.get("/districts", response_model=list[str])
def districts() -> list[str]:
    """Areas this deployment serves (for the sign-up form)."""
    return settings.district_list


# ---------- The patient's own sign-in ----------


@router.post("/patient-login", response_model=PatientTokenOut)
def patient_login(body: PatientLoginIn, request: Request, db: Session = Depends(get_db)) -> PatientTokenOut:
    """Health ID (or any referral code of the patient) + last 4 digits of their phone."""
    patient_login_limiter.check(request.client.host if request.client else "unknown")
    if body.code.startswith("HID-"):
        patient = db.scalar(select(Patient).where(Patient.health_id == body.code))
    else:
        referral = db.scalar(select(Referral).where(Referral.code == body.code))
        patient = db.get(Patient, referral.patient_id) if referral else None
    if patient is None or not patient.phone.endswith(body.phone_last4):
        raise ApiError(404, "NOT_FOUND", "No patient matches this ID and phone number.")
    return PatientTokenOut(token=patient_token_for(patient), patient_id=patient.id, name=patient.name,
                           health_id=patient.health_id, language=patient.language)


@router.get("/me/record", response_model=PatientRecordOut)
def my_record(patient: Patient = Depends(current_patient), db: Session = Depends(get_db)) -> PatientRecordOut:
    """The patient's own history, prescriptions and medicine chart."""
    from app.records import patient_record

    out = patient_record(db, patient)
    db.commit()
    return out


@router.get("/emergency-conditions")
def emergency_conditions() -> list[dict]:
    """What the patient can choose on the emergency screen, with first-aid advice."""
    return [{"condition": c, "service": svc, "label": label, "precautions": tips}
            for c, (svc, label, tips) in EMERGENCY_GUIDE.items()]


@router.post("/emergency", response_model=EmergencyOut, status_code=201)
def emergency(body: EmergencyIn, patient: Patient = Depends(current_patient), db: Session = Depends(get_db)) -> EmergencyOut:
    """Night emergency: the system books the best hospital the ASHA would have chosen."""
    from app.emergency import book

    out = book(db, patient, body)
    commit(db)
    return out
