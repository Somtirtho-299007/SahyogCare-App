"""Public referral status for patients (no account). See docs/WORKFLOW.md, "Patient lookup"."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Facility, Patient, Referral
from app.ratelimit import RateLimiter
from app.rules import PATIENT_CHECKLIST, PUBLIC_LOOKUPS_PER_MINUTE
from app.schemas import PublicLookupIn, PublicLookupOut, PublicStep
from app.timeutil import as_utc

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
    return PublicLookupOut(
        code=referral.code,
        status=referral.status,
        facility_name=facility.name,
        timeline=[PublicStep(status=e.to_status, at=as_utc(e.at)) for e in referral.events],
        checklist=PATIENT_CHECKLIST,
    )
