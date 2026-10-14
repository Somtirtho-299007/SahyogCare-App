"""Night emergency booked by the patient, when the ASHA cannot be reached.

The patient (signed in with their Health ID) picks what is happening, e.g. "labour /
water broke". The system then does what the ASHA would have done:

1. picks the best hospital for that service: free bed in the right ward, distance from
   where the patient is, the service actually running, how reliably it answers;
2. creates the referral under the patient's own record and holds a bed;
3. asks for the hospital's own ambulance when it has one (108 is always shown too);
4. tells the hospital, the ASHA (in the app and by SMS / email, to read when she wakes)
   and the district office; and later, if that hospital rejects, re-routes by itself.

Every step the system takes for the ASHA is recorded with the reason.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import messaging
from app.errors import ApiError
from app.models import AmbulanceTrip, AuditLog, Encounter, Facility, Patient, Referral, User
from app.recommend import recommend
from app.rules import (
    EMERGENCY_GUIDE,
    LOCAL_UTC_OFFSET,
    NATIONAL_AMBULANCE_NUMBER,
    AmbulanceStatus,
    Role,
    Triage,
)
from app.schemas import EmergencyIn, EmergencyOut, RecommendationOut
from app.timeutil import utcnow
from app.workflow import notify, notify_facility_staff

ORIGIN = "PATIENT_EMERGENCY"
FALLBACK_SERVICES = ("Emergency", "General Medicine")


def _best(db: Session, service: str, district: str, lat: float | None, lon: float | None,
          exclude: set[str] | None = None) -> RecommendationOut | None:
    """The best hospital that has a free bed (or no bed data) and is not known to be closed for this."""
    for svc in (service, *[s for s in FALLBACK_SERVICES if s != service]):
        options = recommend(db, svc, district=district, latitude=lat, longitude=lon, exclude=exclude, limit=20)
        usable = [o for o in options if o.service_availability != "UNAVAILABLE"]
        with_bed = [o for o in usable if o.beds_free is None or o.beds_free > 0]
        if with_bed or usable or options:
            return (with_bed or usable or options)[0]
    return None


def _local(dt) -> str:
    return (dt + LOCAL_UTC_OFFSET).strftime("%I:%M %p, %d %b")


def _coordinators(db: Session, district: str) -> list[str]:
    return list(db.scalars(select(User.id).where(
        User.role == Role.COORDINATOR, User.is_active.is_(True), User.approved.is_(True),
        func.lower(User.district) == district.lower())))


def _tell_asha(db: Session, asha: User, referral: Referral, message: str) -> None:
    notify(db, asha.id, referral, "PATIENT_EMERGENCY", message)
    messaging.send_both(phone=asha.phone, email=asha.email, subject="SahyogCare: patient emergency", text=message)


def book(db: Session, patient: Patient, body: EmergencyIn) -> EmergencyOut:
    from app.routers.referrals import _create  # shared referral creation (bed hold, hospital alert)

    if patient.deceased_at is not None:
        raise ApiError(409, "PATIENT_DECEASED", "This record is closed.")
    service, description, precautions = EMERGENCY_GUIDE[body.condition]

    asha = db.get(User, patient.created_by_id)
    # Already on the way to a hospital (booked by the ASHA, or this button pressed twice):
    # don't book a second one — tell that hospital and the ASHA it is now an emergency.
    on_the_way = db.scalar(select(Referral).where(Referral.patient_id == patient.id,
                                                  Referral.status.in_(("CREATED", "ACCEPTED")))
                           .order_by(Referral.created_at.desc()).limit(1))
    if on_the_way is not None:
        facility = db.get(Facility, on_the_way.destination_facility_id)
        if on_the_way.origin != ORIGIN:
            notify_facility_staff(db, facility.id, on_the_way, "PATIENT_EMERGENCY",
                                  f"{on_the_way.code}: the patient pressed EMERGENCY ({description}). "
                                  f"Patient phone: {patient.phone}")
            _tell_asha(db, asha, on_the_way, f"{on_the_way.code}: {patient.name} pressed EMERGENCY at "
                                             f"{_local(utcnow())} ({description}). They are booked at {facility.name}.")
        return _out(db, on_the_way, precautions, [], already_open=True)

    lat = body.latitude if body.latitude is not None else patient.latitude
    lon = body.longitude if body.longitude is not None else patient.longitude
    # Hospitals where the patient already has an open referral (e.g. admitted) are skipped.
    busy = set(db.scalars(select(Referral.destination_facility_id).where(
        Referral.patient_id == patient.id, Referral.status.not_in(("CLOSED", "REJECTED", "REROUTED", "DECEASED")))))
    choice = _best(db, service, asha.district, lat, lon, exclude=busy or None)
    if choice is None:
        raise ApiError(503, "NO_HOSPITAL_FOUND", f"No hospital could be found. Call {NATIONAL_AMBULANCE_NUMBER} now.",
                       {"call": NATIONAL_AMBULANCE_NUMBER})

    now = utcnow()
    reason = description + (f" — {body.note.strip()}" if body.note and body.note.strip() else "")
    enc = Encounter(patient_id=patient.id, created_by_id=asha.id, reason=reason, triage=Triage.EMERGENCY,
                    kind="EMERGENCY")
    db.add(enc)
    db.flush()
    why = "; ".join(choice.reasons[:3]) or "best available"
    note = (f"Booked by the patient at {_local(now)} ({description}). The ASHA could not be reached, so "
            f"SahyogCare chose {choice.facility_name}: {why}.")
    referral = _create(db, actor=None, owner_id=asha.id, patient_id=patient.id, encounter=enc,
                       facility_id=choice.facility_id, requested_service=choice.service,
                       allow_without_bed=True, origin=ORIGIN, note=note)
    enc.referral_id = referral.id

    facility = db.get(Facility, choice.facility_id)
    ambulance_requested = False
    if facility.has_ambulance:
        pickup = (body.pickup_note or patient.address or "Patient's home — call the patient's phone").strip()
        db.add(AmbulanceTrip(referral_id=referral.id, facility_id=facility.id, pickup_note=pickup[:300],
                             requested_by_id=asha.id, status=AmbulanceStatus.REQUESTED))
        ambulance_requested = True
        notify_facility_staff(db, facility.id, referral, "AMBULANCE_REQUESTED",
                              f"{referral.code}: EMERGENCY booked by the patient — please send the ambulance. "
                              f"Pickup: {pickup[:120]}. Patient phone: {patient.phone}")

    _tell_asha(db, asha, referral,
               f"{referral.code}: {patient.name} booked an emergency at {_local(now)} ({description}). "
               f"SahyogCare sent them to {facility.name}" + (" and asked for its ambulance" if ambulance_requested
                                                             else "; they were told to call 108") + ".")
    for cid in _coordinators(db, asha.district):
        notify(db, cid, referral, "PATIENT_EMERGENCY",
               f"{referral.code}: night emergency booked by {patient.name} → {facility.name}.")
    messaging.send(phone=patient.phone, email=patient.email, subject="SahyogCare: emergency booked",
                   text=messaging.text("emergency_patient", patient.language, hospital=facility.name,
                                       phone=facility.phone or "-", code=referral.code))
    db.add(AuditLog(actor_id=None, action="PATIENT_EMERGENCY_BOOKED", target_type="referral", target_id=referral.id))
    return _out(db, referral, precautions, choice.reasons, ambulance_requested=ambulance_requested)


def _out(db: Session, referral: Referral, precautions: list[str], reasons: list[str],
         ambulance_requested: bool | None = None, already_open: bool = False) -> EmergencyOut:
    from app import ambulance, beds

    db.flush()  # the bed hold and ambulance request were just added
    facility = db.get(Facility, referral.destination_facility_id)
    if ambulance_requested is None:
        ambulance_requested = ambulance.open_trip(db, referral) is not None
    return EmergencyOut(
        referral_code=referral.code, hospital_name=facility.name, hospital_phone=facility.phone,
        hospital_address=facility.address, service=referral.requested_service,
        bed_held=beds.active_hold(db, referral) is not None, ambulance_requested=ambulance_requested,
        call=NATIONAL_AMBULANCE_NUMBER, precautions=precautions, reasons=reasons, already_open=already_open,
    )


def auto_reroute(db: Session, referral: Referral, why: str) -> Referral | None:
    """A hospital rejected a patient-booked emergency: send it on to the next best hospital at once."""
    from app.routers.referrals import _create, _tried

    patient = db.get(Patient, referral.patient_id)
    asha = db.get(User, referral.created_by_id)
    choice = _best(db, referral.requested_service, asha.district, patient.latitude, patient.longitude,
                   exclude=_tried(db, referral))
    old_facility = db.get(Facility, referral.destination_facility_id)
    if choice is None:
        _tell_asha(db, asha, referral, f"{referral.code}: {old_facility.name} could not take {patient.name} "
                                       f"({why}) and no other hospital was found. Please call the family now.")
        return None
    encounter = db.get(Encounter, referral.encounter_id)
    new = _create(db, actor=None, owner_id=asha.id, patient_id=patient.id, encounter=encounter,
                  facility_id=choice.facility_id, requested_service=choice.service, allow_without_bed=True,
                  rerouted_from=referral, origin=ORIGIN,
                  note=f"Re-routed automatically by SahyogCare from {referral.code}: {old_facility.name} could "
                       f"not take the patient ({why}).")
    facility = db.get(Facility, choice.facility_id)
    _tell_asha(db, asha, new, f"{new.code}: {old_facility.name} could not take {patient.name} ({why}). "
                              f"SahyogCare sent them on to {facility.name}.")
    messaging.send(phone=patient.phone, email=patient.email, subject="SahyogCare: new hospital",
                   text=messaging.text("emergency_patient", patient.language, hospital=facility.name,
                                       phone=facility.phone or "-", code=new.code))
    return new
