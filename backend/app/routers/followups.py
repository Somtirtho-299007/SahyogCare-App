"""Follow-up checkups: the last step of the loop. See docs/WORKFLOW.md.

The doctor sets a follow-up date when recording the outcome. The ASHA then sends
the patient back for the checkup (/sent), or reports that the patient could not
go (/miss). Only the hospital the patient was referred to confirms that the
checkup happened (/complete), which closes the referral.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Facility, FollowUp, Patient, Referral, User
from app.rules import Role, Status
from app.schemas import FollowUpItemOut, NoteIn
from app.security import require_roles
from app.timeutil import as_utc, utcnow
from app.workflow import commit, move, notify_facility_staff

router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


HOSPITAL_ROLES = (Role.FACILITY_STAFF, Role.DOCTOR)


def _scope(user: User):
    if user.role == Role.WORKER:
        return FollowUp.assigned_to_id == user.id
    if user.role in HOSPITAL_ROLES:
        # Hospital staff and doctors see the checkups due at their own hospital only.
        return FollowUp.referral_id.in_(
            select(Referral.id).where(Referral.destination_facility_id == user.facility_id))
    return FollowUp.assigned_to_id.in_(select(User.id).where(User.district == user.district))


def _item(db: Session, fu: FollowUp) -> FollowUpItemOut:
    referral = db.get(Referral, fu.referral_id, with_for_update=True)
    patient = db.get(Patient, referral.patient_id)
    facility = db.get(Facility, referral.destination_facility_id)
    due = as_utc(fu.due_at)
    return FollowUpItemOut(
        id=fu.id,
        referral_id=referral.id,
        referral_code=referral.code,
        referral_status=referral.status,
        patient_name=patient.name,
        patient_phone=patient.phone,
        facility_name=facility.name,
        due_at=due,
        status=fu.status,
        is_late=fu.status != "COMPLETED" and due < utcnow(),
        sent_at=as_utc(fu.sent_at),
    )


def _get(db: Session, user: User, follow_up_id: str) -> FollowUp:
    fu = db.scalar(select(FollowUp).where(FollowUp.id == follow_up_id, _scope(user)))
    if fu is None:
        raise ApiError(404, "NOT_FOUND", "Not found.")
    return fu


@router.get("", response_model=list[FollowUpItemOut])
def list_follow_ups(
    pending: bool = Query(True, description="Only follow-ups not yet completed"),
    user: User = Depends(require_roles(Role.WORKER, Role.COORDINATOR, Role.FACILITY_STAFF, Role.DOCTOR)),
    db: Session = Depends(get_db),
) -> list[FollowUpItemOut]:
    stmt = select(FollowUp).where(_scope(user)).order_by(FollowUp.due_at)
    if pending:
        stmt = stmt.where(FollowUp.status != "COMPLETED")
    return [_item(db, fu) for fu in db.scalars(stmt.limit(200))]


@router.post("/{follow_up_id}/sent", response_model=FollowUpItemOut)
def sent(follow_up_id: str, body: NoteIn | None = None,
         user: User = Depends(require_roles(Role.WORKER)), db: Session = Depends(get_db)) -> FollowUpItemOut:
    """The ASHA has told the patient to go for the follow-up checkup; the hospital is told to expect them."""
    fu = _get(db, user, follow_up_id)
    if fu.status == "COMPLETED":
        raise ApiError(409, "ALREADY_COMPLETED", "The hospital has already confirmed this checkup.")
    referral = db.get(Referral, fu.referral_id, with_for_update=True)
    patient = db.get(Patient, referral.patient_id)
    fu.sent_at = utcnow()
    note = f" Note: {body.note.strip()}" if body and body.note and body.note.strip() else ""
    notify_facility_staff(db, referral.destination_facility_id, referral, "FOLLOW_UP_SENT",
                          f"{referral.code}: {patient.name} is coming for a follow-up checkup "
                          f"(due {as_utc(fu.due_at):%d %b}).{note}")
    commit(db)
    return _item(db, fu)


@router.post("/{follow_up_id}/complete", response_model=FollowUpItemOut)
def complete(follow_up_id: str, body: NoteIn | None = None,
             user: User = Depends(require_roles(Role.FACILITY_STAFF, Role.DOCTOR)),
             db: Session = Depends(get_db)) -> FollowUpItemOut:
    """The hospital confirms the follow-up checkup happened: close the referral (late checkups count too)."""
    fu = _get(db, user, follow_up_id)
    referral = db.get(Referral, fu.referral_id, with_for_update=True)
    move(db, referral, Status.CLOSED, user, note=(body.note if body else None) or "Follow-up checkup done")
    fu.status, fu.completed_at = "COMPLETED", utcnow()
    commit(db)
    return _item(db, fu)


@router.post("/{follow_up_id}/miss", response_model=FollowUpItemOut)
def miss(follow_up_id: str, body: NoteIn | None = None,
         user: User = Depends(require_roles(Role.WORKER)), db: Session = Depends(get_db)) -> FollowUpItemOut:
    """The patient could not go for the checkup: mark it overdue so the coordinator sees it."""
    fu = _get(db, user, follow_up_id)
    referral = db.get(Referral, fu.referral_id, with_for_update=True)
    move(db, referral, Status.OVERDUE, user, note=(body.note if body else None) or "Patient could not go for the follow-up checkup")
    fu.status = "OVERDUE"
    commit(db)
    return _item(db, fu)
