"""Follow-ups: the ASHA's side of closing the loop. See docs/WORKFLOW.md."""

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
from app.workflow import commit, move

router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


def _scope(user: User):
    if user.role == Role.WORKER:
        return FollowUp.assigned_to_id == user.id
    return FollowUp.assigned_to_id.in_(select(User.id).where(User.district == user.district))


def _item(db: Session, fu: FollowUp) -> FollowUpItemOut:
    referral = db.get(Referral, fu.referral_id)
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
    )


def _get(db: Session, user: User, follow_up_id: str) -> FollowUp:
    fu = db.scalar(select(FollowUp).where(FollowUp.id == follow_up_id, _scope(user)))
    if fu is None:
        raise ApiError(404, "NOT_FOUND", "Not found.")
    return fu


@router.get("", response_model=list[FollowUpItemOut])
def list_follow_ups(
    pending: bool = Query(True, description="Only follow-ups not yet completed"),
    user: User = Depends(require_roles(Role.WORKER, Role.COORDINATOR)),
    db: Session = Depends(get_db),
) -> list[FollowUpItemOut]:
    stmt = select(FollowUp).where(_scope(user)).order_by(FollowUp.due_at)
    if pending:
        stmt = stmt.where(FollowUp.status != "COMPLETED")
    return [_item(db, fu) for fu in db.scalars(stmt.limit(200))]


@router.post("/{follow_up_id}/complete", response_model=FollowUpItemOut)
def complete(follow_up_id: str, body: NoteIn | None = None,
             user: User = Depends(require_roles(Role.WORKER, Role.COORDINATOR)),
             db: Session = Depends(get_db)) -> FollowUpItemOut:
    """The follow-up visit happened: close the referral (late visits count too)."""
    fu = _get(db, user, follow_up_id)
    referral = db.get(Referral, fu.referral_id)
    move(db, referral, Status.CLOSED, user, note=(body.note if body else None) or "Follow-up completed")
    fu.status, fu.completed_at = "COMPLETED", utcnow()
    commit(db)
    return _item(db, fu)


@router.post("/{follow_up_id}/miss", response_model=FollowUpItemOut)
def miss(follow_up_id: str, body: NoteIn | None = None,
         user: User = Depends(require_roles(Role.WORKER)), db: Session = Depends(get_db)) -> FollowUpItemOut:
    """The ASHA could not complete the visit: mark it overdue so the coordinator sees it."""
    fu = _get(db, user, follow_up_id)
    referral = db.get(Referral, fu.referral_id)
    move(db, referral, Status.OVERDUE, user, note=(body.note if body else None) or "Follow-up visit missed")
    fu.status = "OVERDUE"
    commit(db)
    return _item(db, fu)
