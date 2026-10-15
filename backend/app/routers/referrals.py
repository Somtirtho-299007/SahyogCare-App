"""Referrals: create, list, move through the state machine, referral passes.

See docs/WORKFLOW.md sections 4–6.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import get_patient_for, get_referral_for, referral_scope
from app.db import get_db
from app.errors import ApiError
from app import beds
from app.models import AuditLog, Encounter, Facility, FacilityService, FollowUp, IdempotencyKey, Referral, ReferralEvent, User
from app.passes import make_pass, read_pass
from app.rules import (
    FINISHED_STATUSES,
    MARKS_SERVICE_UNAVAILABLE,
    REJECTION_LABELS,
    REROUTABLE_STATUSES,
    URGENCY_ORDER,
    RejectionReason,
    Role,
    Status,
    is_open,
    new_referral_code,
    ward_for_service,
)
from app.recommend import recommend
from app.schemas import (
    NoteIn,
    OutcomeIn,
    PassOut,
    PassVerifyIn,
    PassVerifyOut,
    ReferralIn,
    RecommendationOut,
    ReferralOut,
    RejectIn,
    RejectionReasonOut,
    RerouteIn,
)
from app.security import current_user, require_roles
from app.timeutil import as_utc, utcnow
from app.workflow import commit, move, notify_facility_staff, referral_out, rerouted_to, set_service_availability

router = APIRouter(tags=["referrals"])


# ---------- Create ----------


def _no_beds_error(db: Session, facility: Facility, service: str, state, creator: User,
                   exclude: set[str]) -> ApiError:
    """The chosen hospital is full: say so, and offer the next best hospitals straight away."""
    alternatives = recommend(db, service, district=creator.district, exclude=exclude, limit=3)
    return ApiError(
        409, "NO_BEDS_AVAILABLE",
        f"{facility.name} reports no free {state.ward.ward.lower()} bed. Choose another hospital, "
        "or send anyway if this is the only option.",
        {"ward": state.ward.ward, "facility_id": facility.id,
         "alternatives": [a.model_dump(mode="json") for a in alternatives]},
    )


def _create(db: Session, *, actor: User, owner_id: str, patient_id: str, encounter: Encounter,
            facility_id: str, requested_service: str, allow_without_bed: bool,
            rerouted_from: Referral | None = None) -> Referral:
    """Create a referral and hold a bed for it. Shared by "new referral" and "send elsewhere"."""
    facility = db.get(Facility, facility_id)
    owner = db.get(User, owner_id)
    # Referrals stay inside the ASHA's own area.
    if facility is None or not facility.active or facility.district.lower() != owner.district.lower():
        raise ApiError(404, "NOT_FOUND", "Facility not found.")
    service = db.scalar(
        select(FacilityService.service).where(
            FacilityService.facility_id == facility.id, func.lower(FacilityService.service) == requested_service.lower()
        )
    )
    if service is None:
        raise ApiError(422, "SERVICE_NOT_LISTED", f"{facility.name} does not list {requested_service}.")

    duplicate = db.scalar(
        select(Referral.id).where(
            Referral.patient_id == patient_id,
            Referral.destination_facility_id == facility.id,
            Referral.status.not_in(FINISHED_STATUSES),
        )
    )
    if duplicate:
        raise ApiError(409, "DUPLICATE_REFERRAL", "This patient already has an open referral to this facility.",
                       {"referral_id": duplicate})

    ward = ward_for_service(service)
    state = beds.ward_state(db, facility.id, ward, lock=True) if ward else None
    if state is not None and state.free <= 0 and not allow_without_bed:
        exclude = {facility.id}
        if rerouted_from is not None:
            exclude.add(rerouted_from.destination_facility_id)
        raise _no_beds_error(db, facility, service, state, db.get(User, owner_id), exclude)

    code = new_referral_code()
    while db.scalar(select(Referral.id).where(Referral.code == code)):
        code = new_referral_code()

    referral = Referral(
        code=code,
        patient_id=patient_id,
        encounter_id=encounter.id,
        created_by_id=owner_id,
        destination_facility_id=facility.id,
        requested_service=service,
        reason=encounter.reason,
        triage=encounter.triage,
        status=Status.CREATED,
        rerouted_from_id=rerouted_from.id if rerouted_from else None,
    )
    db.add(referral)
    db.flush()
    note = f"Sent on from {rerouted_from.code}" if rerouted_from else None
    referral.events.append(ReferralEvent(from_status=None, to_status=Status.CREATED, actor_id=actor.id, note=note))
    db.add(AuditLog(actor_id=actor.id, action="REFERRAL_CREATED", target_type="referral", target_id=referral.id))
    if state is not None and state.free > 0:
        beds.place_hold(db, referral, state)

    bed_note = "a bed is held" if state is not None and state.free > 0 else "no bed could be held"
    notify_facility_staff(
        db, facility.id, referral, "NEW_REFERRAL",
        f"{referral.code}: new {referral.triage.lower()} referral for {service} ({bed_note}).",
    )
    return referral


@router.post("/referrals", response_model=ReferralOut, status_code=201)
def create_referral(
    body: ReferralIn,
    idempotency_key: str | None = Header(None, max_length=100),
    user: User = Depends(require_roles(Role.WORKER)),
    db: Session = Depends(get_db),
) -> ReferralOut:
    scoped_key = f"{user.id}:{idempotency_key}" if idempotency_key else None
    if scoped_key:
        seen = db.get(IdempotencyKey, scoped_key)
        if seen is not None:
            # Same request sent twice (e.g. a retry on a bad network): return the first result.
            return referral_out(db, db.get(Referral, seen.response["referral_id"]))

    patient = get_patient_for(db, user, body.patient_id)
    encounter = db.get(Encounter, body.encounter_id)
    if encounter is None or encounter.patient_id != patient.id:
        raise ApiError(404, "NOT_FOUND", "Encounter not found for this patient.")

    referral = _create(db, actor=user, owner_id=user.id, patient_id=patient.id, encounter=encounter,
                       facility_id=body.destination_facility_id, requested_service=body.requested_service,
                       allow_without_bed=body.allow_without_bed)
    if scoped_key:
        db.add(IdempotencyKey(key=scoped_key, user_id=user.id, response={"referral_id": referral.id}))
    commit(db)
    db.refresh(referral)
    return referral_out(db, referral)


# ---------- Re-routing: send the patient to another hospital ----------


@router.get("/referrals/{referral_id}/alternatives", response_model=list[RecommendationOut])
def alternatives(
    referral_id: str,
    latitude: float | None = Query(None, ge=-90, le=90, description="Where the patient is now, if known"),
    longitude: float | None = Query(None, ge=-180, le=180),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[RecommendationOut]:
    """Other hospitals for the same service, best first (excludes every hospital already tried)."""
    referral = get_referral_for(db, user, referral_id)
    owner = db.get(User, referral.created_by_id)
    return recommend(db, referral.requested_service, district=owner.district, latitude=latitude,
                     longitude=longitude, exclude=_tried(db, referral))


def _tried(db: Session, referral: Referral) -> set[str]:
    """Hospitals this patient was already sent to along the re-routing chain."""
    tried, current = set(), referral
    while current is not None:
        tried.add(current.destination_facility_id)
        current = db.get(Referral, current.rerouted_from_id) if current.rerouted_from_id else None
    return tried


@router.post("/referrals/{referral_id}/reroute", response_model=ReferralOut, status_code=201)
def reroute(
    referral_id: str,
    body: RerouteIn,
    user: User = Depends(require_roles(Role.WORKER, Role.COORDINATOR)),
    db: Session = Depends(get_db),
) -> ReferralOut:
    """Send the patient to another hospital. The old referral ends as REROUTED (or stays REJECTED),
    its bed and ambulance are released, and a new referral with a new code continues the journey."""
    old = get_referral_for(db, user, referral_id)
    if rerouted_to(db, old) is not None:
        raise ApiError(409, "ALREADY_REROUTED", "This referral was already sent to another hospital.")
    if old.status not in REROUTABLE_STATUSES:
        raise ApiError(409, "INVALID_STATE_TRANSITION",
                       "Only referrals that are waiting, accepted or rejected can be sent elsewhere.",
                       {"current_status": old.status})
    if body.destination_facility_id == old.destination_facility_id:
        raise ApiError(422, "SAME_FACILITY", "Choose a different hospital.")

    encounter = db.get(Encounter, old.encounter_id)
    new = _create(db, actor=user, owner_id=old.created_by_id, patient_id=old.patient_id, encounter=encounter,
                  facility_id=body.destination_facility_id,
                  requested_service=body.requested_service or old.requested_service,
                  allow_without_bed=body.allow_without_bed, rerouted_from=old)
    if old.status != Status.REJECTED:
        old_facility = db.get(Facility, old.destination_facility_id)
        move(db, old, Status.REROUTED, user, note=body.note or f"Sent on as {new.code}")
        notify_facility_staff(db, old_facility.id, old, "REFERRAL_WITHDRAWN",
                              f"{old.code}: the patient is being sent to another hospital. The held bed is released.")
    db.add(AuditLog(actor_id=user.id, action="REFERRAL_REROUTED", target_type="referral", target_id=old.id))
    commit(db)
    db.refresh(new)
    return referral_out(db, new)


# ---------- Read ----------


@router.get("/referrals", response_model=list[ReferralOut])
def list_referrals(
    status: Status | None = None,
    open_only: bool = Query(False, alias="open"),
    triage: str | None = Query(None, pattern="^(EMERGENCY|PRIORITY|ROUTINE)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[ReferralOut]:
    stmt = select(Referral).where(referral_scope(user)).order_by(Referral.created_at)
    if status:
        stmt = stmt.where(Referral.status == status)
    if open_only:
        stmt = stmt.where(Referral.status.not_in(FINISHED_STATUSES))
    if triage:
        stmt = stmt.where(Referral.triage == triage)
    referrals = list(db.scalars(stmt.limit(200)))
    # Most urgent first; within the same urgency, the one waiting longest first.
    referrals.sort(key=lambda r: (not is_open(r.status), URGENCY_ORDER.get(r.triage, 9)))
    return [referral_out(db, r) for r in referrals]


@router.get("/referrals/{referral_id}", response_model=ReferralOut)
def get_referral(referral_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ReferralOut:
    return referral_out(db, get_referral_for(db, user, referral_id))


@router.get("/referral-rejection-reasons", response_model=list[RejectionReasonOut])
def rejection_reasons(_: User = Depends(current_user)) -> list[RejectionReasonOut]:
    return [
        RejectionReasonOut(code=r, label=REJECTION_LABELS[r], marks_service_unavailable=r in MARKS_SERVICE_UNAVAILABLE)
        for r in RejectionReason
    ]


# ---------- Status changes ----------


@router.post("/referrals/{referral_id}/accept", response_model=ReferralOut)
def accept(referral_id: str, body: NoteIn | None = None, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> ReferralOut:
    referral = get_referral_for(db, user, referral_id)
    move(db, referral, Status.ACCEPTED, user, note=body.note if body else None)
    set_service_availability(db, referral, "AVAILABLE", "Accepted a referral")
    commit(db)
    return referral_out(db, referral)


@router.post("/referrals/{referral_id}/reject", response_model=ReferralOut)
def reject(referral_id: str, body: RejectIn, user: User = Depends(current_user),
           db: Session = Depends(get_db)) -> ReferralOut:
    reason = RejectionReason(body.reason)
    if reason == RejectionReason.OTHER and not (body.note and body.note.strip()):
        raise ApiError(422, "VALIDATION_ERROR", "Please add a note explaining the reason.", {"fields": {"note": "Required"}})
    referral = get_referral_for(db, user, referral_id)
    move(db, referral, Status.REJECTED, user, note=body.note)
    referral.rejection_reason = reason
    if reason in MARKS_SERVICE_UNAVAILABLE:
        set_service_availability(db, referral, "UNAVAILABLE", REJECTION_LABELS[reason])
    if reason == RejectionReason.NO_BEDS:
        beds.mark_ward_full(db, referral)
    commit(db)
    return referral_out(db, referral)


@router.post("/referrals/{referral_id}/arrival", response_model=ReferralOut)
def arrival(referral_id: str, body: NoteIn | None = None, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> ReferralOut:
    referral = get_referral_for(db, user, referral_id)
    move(db, referral, Status.ARRIVAL_RECORDED, user, note=body.note if body else None)
    commit(db)
    return referral_out(db, referral)


@router.post("/referrals/{referral_id}/consultation", response_model=ReferralOut)
def consultation(referral_id: str, body: NoteIn | None = None, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> ReferralOut:
    referral = get_referral_for(db, user, referral_id)
    move(db, referral, Status.CONSULTED, user, note=body.note if body else None)
    commit(db)
    return referral_out(db, referral)


@router.post("/referrals/{referral_id}/outcome", response_model=ReferralOut)
def outcome(referral_id: str, body: OutcomeIn | None = None, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> ReferralOut:
    body = body or OutcomeIn()
    referral = get_referral_for(db, user, referral_id)
    move(db, referral, Status.OUTCOME_RECORDED, user, note=body.note)
    # The server then hands the case back to the ASHA as a follow-up.
    referral.follow_up_days = body.follow_up_days
    db.add(FollowUp(referral_id=referral.id, assigned_to_id=referral.created_by_id,
                    due_at=utcnow() + timedelta(days=body.follow_up_days)))
    move(db, referral, Status.FOLLOW_UP_DUE, None)
    commit(db)
    return referral_out(db, referral)


@router.post("/referrals/{referral_id}/close", response_model=ReferralOut)
def close(referral_id: str, body: NoteIn | None = None, user: User = Depends(current_user),
          db: Session = Depends(get_db)) -> ReferralOut:
    referral = get_referral_for(db, user, referral_id)
    move(db, referral, Status.CLOSED, user, note=body.note if body else None)
    for fu in db.scalars(select(FollowUp).where(FollowUp.referral_id == referral.id, FollowUp.status != "COMPLETED")):
        fu.status, fu.completed_at = "COMPLETED", utcnow()
    commit(db)
    return referral_out(db, referral)


@router.post("/referrals/{referral_id}/escalate", response_model=ReferralOut)
def escalate(referral_id: str, body: NoteIn | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)) -> ReferralOut:
    """Coordinator takes over an overdue follow-up."""
    referral = get_referral_for(db, user, referral_id)
    move(db, referral, Status.ESCALATED, user, note=body.note if body else None)
    for fu in db.scalars(select(FollowUp).where(FollowUp.referral_id == referral.id, FollowUp.status == "OVERDUE")):
        fu.status = "ESCALATED"
    commit(db)
    return referral_out(db, referral)


# ---------- Referral pass ----------


@router.get("/referrals/{referral_id}/pass", response_model=PassOut)
def get_pass(referral_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> PassOut:
    referral = get_referral_for(db, user, referral_id)
    if not is_open(referral.status):
        raise ApiError(409, "REFERRAL_NOT_OPEN", "Passes are only issued for open referrals.")
    return PassOut(code=referral.code, qr_text=make_pass(referral))


@router.post("/referral-passes/verify", response_model=PassVerifyOut)
def verify_pass(body: PassVerifyIn, user: User = Depends(require_roles(Role.FACILITY_STAFF)),
                db: Session = Depends(get_db)) -> PassVerifyOut:
    data = read_pass(body.qr_text)
    if data["f"] != user.facility_id:
        raise ApiError(403, "PASS_WRONG_FACILITY", "This referral pass is for a different facility.")
    referral = db.scalar(select(Referral).where(Referral.code == data["c"], Referral.destination_facility_id == user.facility_id))
    if referral is None:
        raise ApiError(404, "NOT_FOUND", "Referral not found.")

    now = utcnow()
    source, at = "ONLINE", None
    if body.scanned_at is not None:
        scanned = as_utc(body.scanned_at)
        if scanned > now + timedelta(minutes=5):
            raise ApiError(422, "VALIDATION_ERROR", "Scan time is in the future.", {"fields": {"scanned_at": "In the future"}})
        # Keep the timeline in order: a scan can't be earlier than what already happened.
        last = max(as_utc(e.at) for e in referral.events)
        source, at = "OFFLINE_PASS", max(scanned, last)

    if referral.status == Status.REJECTED:
        code = "SYNC_CONFLICT" if body.scanned_at else "INVALID_STATE_TRANSITION"
        raise ApiError(409, code, "This referral was rejected by the facility.", {"current_status": referral.status})

    already = referral.status not in (Status.CREATED, Status.ACCEPTED)
    if referral.status == Status.CREATED:
        move(db, referral, Status.ACCEPTED, user, note="Accepted on arrival (pass scanned)", source=source, at=at)
        set_service_availability(db, referral, "AVAILABLE", "Accepted a referral")
    if referral.status == Status.ACCEPTED:
        move(db, referral, Status.ARRIVAL_RECORDED, user, note="Referral pass scanned", source=source, at=at)
    commit(db)
    db.refresh(referral)
    return PassVerifyOut(referral=referral_out(db, referral), already_recorded=already)
