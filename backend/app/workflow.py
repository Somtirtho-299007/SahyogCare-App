"""Moving referrals through the state machine, and describing them to the frontend.

Every status change goes through `move()`, which checks the rules, appends a
referral_event, writes the audit log and tells the ASHA — all in the caller's
database transaction, so either everything is saved or nothing is.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import (
    AuditLog,
    Encounter,
    Facility,
    FacilityService,
    FollowUp,
    Notification,
    Patient,
    Referral,
    ReferralEvent,
    User,
)
from app.rules import SYSTEM, Status, TransitionError, check_transition, is_open
from app.schemas import EventOut, FacilityBrief, FollowUpOut, PatientOut, ReferralOut, Vitals
from app.timeutil import as_utc, utcnow

STATUS_MESSAGES = {
    Status.ACCEPTED: "{code}: {patient} was accepted by {facility}.",
    Status.REJECTED: "{code}: {facility} could not take {patient}. Please choose another facility.",
    Status.ARRIVAL_RECORDED: "{code}: {patient} has arrived at {facility}.",
    Status.CONSULTED: "{code}: {patient} has been seen by a doctor.",
    Status.OUTCOME_RECORDED: "{code}: the outcome for {patient} has been recorded.",
    Status.FOLLOW_UP_DUE: "{code}: a follow-up visit for {patient} is due.",
    Status.OVERDUE: "{code}: the follow-up for {patient} is overdue.",
    Status.ESCALATED: "{code}: the overdue follow-up for {patient} was escalated by the coordinator.",
    Status.CLOSED: "{code}: the referral for {patient} is closed.",
}


def notify(db: Session, user_id: str, referral: Referral | None, kind: str, message: str) -> bool:
    """Add an alert unless this user already has one of this kind for this referral."""
    rid = referral.id if referral else None
    exists_already = db.scalar(
        select(Notification.id).where(
            Notification.user_id == user_id, Notification.referral_id == rid, Notification.kind == kind
        )
    )
    if exists_already is not None:
        return False
    db.add(Notification(user_id=user_id, referral_id=rid, kind=kind, message=message))
    return True


def move(
    db: Session,
    referral: Referral,
    target: Status,
    actor: User | None,
    note: str | None = None,
    source: str = "ONLINE",
    at: datetime | None = None,
) -> None:
    """Change a referral's status. `actor=None` means the system itself."""
    try:
        check_transition(actor.role if actor else SYSTEM, referral.status, target)
    except TransitionError as exc:
        status = 409 if exc.code == "INVALID_STATE_TRANSITION" else 403
        raise ApiError(status, exc.code, exc.message, {"current_status": referral.status}) from exc

    # Appended through the relationship so referral.events is current within this request.
    referral.events.append(
        ReferralEvent(
            from_status=referral.status,
            to_status=target,
            actor_id=actor.id if actor else None,
            note=note,
            source=source if actor else "SYSTEM",
            at=at or utcnow(),
        )
    )
    referral.status = target
    referral.updated_at = utcnow()
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            action=f"REFERRAL_{target}",
            target_type="referral",
            target_id=referral.id,
        )
    )
    _notify_creator(db, referral, target, actor)


def _notify_creator(db: Session, referral: Referral, target: Status, actor: User | None) -> None:
    template = STATUS_MESSAGES.get(target)
    if template is None or (actor is not None and actor.id == referral.created_by_id):
        return
    patient = db.get(Patient, referral.patient_id)
    facility = db.get(Facility, referral.destination_facility_id)
    message = template.format(code=referral.code, patient=patient.name, facility=facility.name)
    notify(db, referral.created_by_id, referral, f"STATUS_{target}", message)


def set_service_availability(
    db: Session, referral: Referral, availability: str, note: str | None
) -> None:
    """Learning from the facility's answer: what it accepted or refused tells us what it can do now."""
    svc = db.scalar(
        select(FacilityService).where(
            FacilityService.facility_id == referral.destination_facility_id,
            FacilityService.service.ilike(referral.requested_service),
        )
    )
    if svc is None:
        return
    svc.availability = availability
    svc.availability_note = note
    svc.availability_updated_at = utcnow()
    svc.learned_from_referral_id = referral.id


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "CONFLICT", "This change conflicts with another one. Please refresh and try again.") from exc


# ---------- Describing a referral ----------


def _vitals(enc: Encounter) -> Vitals:
    return Vitals(**{f: getattr(enc, f) for f in Vitals.model_fields})


def referral_out(db: Session, referral: Referral) -> ReferralOut:
    patient = db.get(Patient, referral.patient_id)
    facility = db.get(Facility, referral.destination_facility_id)
    encounter = db.get(Encounter, referral.encounter_id)
    roles = {u.id: u.role for u in db.scalars(select(User).where(User.id.in_({e.actor_id for e in referral.events if e.actor_id})))}
    follow_up = db.scalar(
        select(FollowUp).where(FollowUp.referral_id == referral.id).order_by(FollowUp.created_at.desc()).limit(1)
    )
    return ReferralOut(
        id=referral.id,
        code=referral.code,
        status=referral.status,
        is_open=is_open(referral.status),
        triage=referral.triage,
        requested_service=referral.requested_service,
        reason=referral.reason,
        rejection_reason=referral.rejection_reason,
        created_at=as_utc(referral.created_at),
        updated_at=as_utc(referral.updated_at),
        patient=PatientOut.model_validate(patient),
        facility=FacilityBrief(id=facility.id, name=facility.name, phone=facility.phone),
        vitals=_vitals(encounter),
        events=[
            EventOut(
                from_status=e.from_status,
                to_status=e.to_status,
                at=as_utc(e.at),
                note=e.note,
                source=e.source,
                actor_role=roles.get(e.actor_id),
            )
            for e in referral.events
        ],
        follow_up=FollowUpOut(due_at=as_utc(follow_up.due_at), status=follow_up.status) if follow_up else None,
    )
