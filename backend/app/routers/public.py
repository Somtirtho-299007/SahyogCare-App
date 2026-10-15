"""Public referral status for patients (no account). See docs/WORKFLOW.md, "Patient lookup"."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app import ambulance
from app.models import Facility, Patient, Referral
from app.config import settings
from app.ratelimit import RateLimiter
from app.rules import NATIONAL_AMBULANCE_NUMBER, PATIENT_CHECKLIST, PUBLIC_LOOKUPS_PER_MINUTE
from app.schemas import PublicAmbulance, PublicLookupIn, PublicLookupOut, PublicStep
from app.timeutil import as_utc
from app.workflow import rerouted_to

router = APIRouter(prefix="/public", tags=["public"])
lookup_limiter = RateLimiter(PUBLIC_LOOKUPS_PER_MINUTE)


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
