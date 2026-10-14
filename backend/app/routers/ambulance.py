"""Ambulance for a referred patient: the ASHA asks, the receiving hospital sends its ambulance.

When the hospital has no ambulance, or does not send one in time, everyone is
pointed to the national ambulance number (108) instead of waiting.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import ambulance, messaging
from app.access import get_referral_for
from app.db import get_db
from app.errors import ApiError
from app.models import AmbulanceTrip, AuditLog, Facility, Patient, User
from app.rules import NATIONAL_AMBULANCE_NUMBER, AmbulanceStatus, Role, Status
from app.schemas import AmbulanceCancelIn, AmbulanceDispatchIn, AmbulanceRequestIn, ReferralOut
from app.security import require_roles
from app.timeutil import utcnow
from app.workflow import commit, move, notify, notify_facility_staff, referral_out

router = APIRouter(prefix="/referrals/{referral_id}/ambulance", tags=["ambulance"])

# The patient is still to be fetched only before arrival.
FETCHABLE = (Status.CREATED, Status.ACCEPTED)


def _audit(db: Session, user: User, action: str, trip: AmbulanceTrip) -> None:
    db.add(AuditLog(actor_id=user.id, action=action, target_type="ambulance_trip", target_id=trip.id))


@router.post("", response_model=ReferralOut, status_code=201)
def request_ambulance(referral_id: str, body: AmbulanceRequestIn,
                      user: User = Depends(require_roles(Role.WORKER, Role.COORDINATOR)),
                      db: Session = Depends(get_db)) -> ReferralOut:
    referral = get_referral_for(db, user, referral_id, lock=True)
    if referral.status not in FETCHABLE:
        raise ApiError(409, "INVALID_STATE_TRANSITION", "An ambulance can only be requested before the patient arrives.",
                       {"current_status": referral.status})
    if ambulance.open_trip(db, referral) is not None:
        raise ApiError(409, "AMBULANCE_ALREADY_REQUESTED", "An ambulance is already requested for this referral.")
    facility = db.get(Facility, referral.destination_facility_id)
    if not facility.has_ambulance:
        raise ApiError(422, "NO_HOSPITAL_AMBULANCE",
                       f"{facility.name} has no ambulance of its own. Call {NATIONAL_AMBULANCE_NUMBER}.",
                       {"call": NATIONAL_AMBULANCE_NUMBER})
    trip = AmbulanceTrip(referral_id=referral.id, facility_id=facility.id, pickup_note=body.pickup_note.strip(),
                         requested_by_id=user.id, status=AmbulanceStatus.REQUESTED)
    db.add(trip)
    db.flush()
    _audit(db, user, "AMBULANCE_REQUESTED", trip)
    notify_facility_staff(db, facility.id, referral, "AMBULANCE_REQUESTED",
                          f"{referral.code}: ambulance requested ({referral.triage.lower()}). Pickup: {trip.pickup_note}")
    commit(db)
    return referral_out(db, referral)


@router.post("/dispatch", response_model=ReferralOut)
def dispatch(referral_id: str, body: AmbulanceDispatchIn,
             user: User = Depends(require_roles(Role.FACILITY_STAFF)),
             db: Session = Depends(get_db)) -> ReferralOut:
    referral = get_referral_for(db, user, referral_id, lock=True)
    trip = ambulance.open_trip(db, referral)
    if trip is None or trip.status != AmbulanceStatus.REQUESTED:
        raise ApiError(409, "INVALID_STATE_TRANSITION", "No ambulance request is waiting for this referral.")
    if referral.status == Status.CREATED:
        # Sending the ambulance means the hospital is taking the patient.
        move(db, referral, Status.ACCEPTED, user, note="Accepted (ambulance sent)")
    trip.status, trip.dispatched_at = AmbulanceStatus.DISPATCHED, utcnow()
    trip.eta_minutes, trip.vehicle_number, trip.driver_phone = body.eta_minutes, body.vehicle_number, body.driver_phone
    _audit(db, user, "AMBULANCE_DISPATCHED", trip)
    patient = db.get(Patient, referral.patient_id)
    notify(db, referral.created_by_id, referral, "AMBULANCE_DISPATCHED",
           f"{referral.code}: ambulance on the way for {patient.name}, about {body.eta_minutes} min."
           + (f" Driver: {body.driver_phone}." if body.driver_phone else ""))
    # The family gets the vehicle number and driver's phone by SMS (or email), in their language.
    messaging.send(phone=patient.phone, email=patient.email, subject="SahyogCare: ambulance on the way",
                   text=messaging.text("ambulance", patient.language, vehicle=body.vehicle_number or "",
                                       name=patient.name, eta=body.eta_minutes, driver=body.driver_phone or "-"))
    commit(db)
    return referral_out(db, referral)


@router.post("/picked-up", response_model=ReferralOut)
def picked_up(referral_id: str, user: User = Depends(require_roles(Role.FACILITY_STAFF, Role.WORKER)),
              db: Session = Depends(get_db)) -> ReferralOut:
    referral = get_referral_for(db, user, referral_id, lock=True)
    trip = ambulance.open_trip(db, referral)
    if trip is None or trip.status != AmbulanceStatus.DISPATCHED:
        raise ApiError(409, "INVALID_STATE_TRANSITION", "No ambulance is on its way for this referral.")
    trip.status, trip.picked_up_at = AmbulanceStatus.PICKED_UP, utcnow()
    _audit(db, user, "AMBULANCE_PICKED_UP", trip)
    commit(db)
    return referral_out(db, referral)


@router.post("/cancel", response_model=ReferralOut)
def cancel(referral_id: str, body: AmbulanceCancelIn,
           user: User = Depends(require_roles(Role.WORKER, Role.FACILITY_STAFF, Role.COORDINATOR)),
           db: Session = Depends(get_db)) -> ReferralOut:
    referral = get_referral_for(db, user, referral_id, lock=True)
    trip = ambulance.open_trip(db, referral)
    if trip is None:
        raise ApiError(409, "INVALID_STATE_TRANSITION", "No ambulance trip is open for this referral.")
    ambulance.cancel_open(db, referral, body.reason.strip())
    _audit(db, user, "AMBULANCE_CANCELLED", trip)
    if user.role == Role.FACILITY_STAFF:
        notify(db, referral.created_by_id, referral, "AMBULANCE_CANCELLED",
               f"{referral.code}: the hospital cannot send its ambulance ({body.reason.strip()}). "
               f"Call {NATIONAL_AMBULANCE_NUMBER}.")
    else:
        notify_facility_staff(db, referral.destination_facility_id, referral, "AMBULANCE_CANCELLED",
                              f"{referral.code}: ambulance no longer needed ({body.reason.strip()}).")
    commit(db)
    return referral_out(db, referral)
