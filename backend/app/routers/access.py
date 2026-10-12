"""Self sign-up: a new user asks for a role, the coordinator approves it in one tap.

Anyone can log in with their own email (app/routers/auth.py). Until approved
they see no records. They ask for a role here — ASHA, hospital staff (with
their hospital), doctor (with their hospital) or coordinator — and every
coordinator of the district is alerted. ASHAs can be approved automatically
with SAHYOG_AUTO_APPROVE_ASHA=true, because an ASHA only ever sees her own
patients; the other roles see other people's patients and always need a person
to approve them.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import ApiError
from app.models import AccessRequest, AuditLog, Facility, Notification, User
from app.rules import Role
from app.security import current_user_any, require_roles
from app.timeutil import as_utc, utcnow
from app.workflow import commit

router = APIRouter(prefix="/access-requests", tags=["access requests"])

HOSPITAL_ROLES = {Role.FACILITY_STAFF, Role.DOCTOR}


class AccessRequestIn(BaseModel):
    role: Literal["WORKER", "FACILITY_STAFF", "DOCTOR", "COORDINATOR"]
    name: str = Field(min_length=1, max_length=120)
    # Required for hospital staff and doctors.
    facility_id: str | None = None
    note: str | None = Field(None, max_length=300, description="Anything that helps the coordinator check who you are")


class DecisionIn(BaseModel):
    note: str | None = Field(None, max_length=300)


class AccessRequestOut(BaseModel):
    id: str
    email: str
    name: str
    requested_role: str
    facility_id: str | None
    facility_name: str | None
    note: str | None
    status: str  # PENDING | APPROVED | REJECTED
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None


def _out(db: Session, r: AccessRequest) -> AccessRequestOut:
    user = db.get(User, r.user_id)
    facility = db.get(Facility, r.facility_id) if r.facility_id else None
    return AccessRequestOut(
        id=r.id, email=user.email, name=r.name, requested_role=r.requested_role, facility_id=r.facility_id,
        facility_name=facility.name if facility else None, note=r.note, status=r.status,
        decision_note=r.decision_note, created_at=as_utc(r.created_at), decided_at=as_utc(r.decided_at),
    )


def _apply(user: User, r: AccessRequest) -> None:
    user.role, user.facility_id, user.name, user.approved = r.requested_role, r.facility_id, r.name, True


@router.post("", response_model=AccessRequestOut, status_code=201)
def ask_for_role(body: AccessRequestIn, user: User = Depends(current_user_any),
                 db: Session = Depends(get_db)) -> AccessRequestOut:
    if body.role in HOSPITAL_ROLES:
        facility = db.get(Facility, body.facility_id) if body.facility_id else None
        if facility is None or facility.district.lower() != user.district.lower():
            raise ApiError(422, "VALIDATION_ERROR", "Choose the hospital you work at.",
                           {"fields": {"facility_id": "Required"}})
    elif body.facility_id is not None:
        raise ApiError(422, "VALIDATION_ERROR", "Only hospital staff and doctors choose a hospital.",
                       {"fields": {"facility_id": "Not allowed for this role"}})

    # A new request replaces any that is still waiting.
    for old in db.scalars(select(AccessRequest).where(AccessRequest.user_id == user.id,
                                                      AccessRequest.status == "PENDING")):
        db.delete(old)
    r = AccessRequest(user_id=user.id, requested_role=body.role, facility_id=body.facility_id,
                      name=body.name.strip(), note=body.note, status="PENDING")
    db.add(r)
    db.flush()

    if body.role == Role.WORKER and settings.auto_approve_asha:
        r.status, r.decided_at, r.decision_note = "APPROVED", utcnow(), "Approved automatically (ASHA)"
        _apply(user, r)
    else:
        coordinators = db.scalars(select(User.id).where(
            User.role == Role.COORDINATOR, User.approved.is_(True), User.is_active.is_(True),
            func.lower(User.district) == user.district.lower(),
        ))
        for cid in coordinators:
            db.add(Notification(user_id=cid, referral_id=None, kind="ACCESS_REQUEST",
                                message=f"{r.name} ({user.email}) asks to join as "
                                        f"{body.role.replace('_', ' ').lower()}."))
    db.add(AuditLog(actor_id=user.id, action="ACCESS_REQUESTED", target_type="access_request", target_id=r.id))
    commit(db)
    return _out(db, r)


@router.get("/mine", response_model=AccessRequestOut | None)
def my_request(user: User = Depends(current_user_any), db: Session = Depends(get_db)) -> AccessRequestOut | None:
    r = db.scalar(select(AccessRequest).where(AccessRequest.user_id == user.id)
                  .order_by(AccessRequest.created_at.desc()).limit(1))
    return _out(db, r) if r else None


@router.get("", response_model=list[AccessRequestOut])
def list_requests(status: Literal["PENDING", "APPROVED", "REJECTED"] = Query("PENDING"),
                  coordinator: User = Depends(require_roles(Role.COORDINATOR)),
                  db: Session = Depends(get_db)) -> list[AccessRequestOut]:
    rows = db.scalars(
        select(AccessRequest).join(User, User.id == AccessRequest.user_id)
        .where(AccessRequest.status == status, func.lower(User.district) == coordinator.district.lower())
        .order_by(AccessRequest.created_at)
    )
    return [_out(db, r) for r in rows]


def _pending(db: Session, coordinator: User, request_id: str) -> tuple[AccessRequest, User]:
    r = db.get(AccessRequest, request_id)
    user = db.get(User, r.user_id) if r else None
    if r is None or user.district.lower() != coordinator.district.lower():
        raise ApiError(404, "NOT_FOUND", "Not found.")
    if r.status != "PENDING":
        raise ApiError(409, "ALREADY_DECIDED", f"This request was already {r.status.lower()}.")
    return r, user


@router.post("/{request_id}/approve", response_model=AccessRequestOut)
def approve(request_id: str, body: DecisionIn | None = None,
            coordinator: User = Depends(require_roles(Role.COORDINATOR)),
            db: Session = Depends(get_db)) -> AccessRequestOut:
    r, user = _pending(db, coordinator, request_id)
    r.status, r.decided_by_id, r.decided_at = "APPROVED", coordinator.id, utcnow()
    r.decision_note = body.note if body else None
    _apply(user, r)
    db.add(AuditLog(actor_id=coordinator.id, action="ACCESS_APPROVED", target_type="user", target_id=user.id))
    commit(db)
    return _out(db, r)


@router.post("/{request_id}/reject", response_model=AccessRequestOut)
def reject(request_id: str, body: DecisionIn | None = None,
           coordinator: User = Depends(require_roles(Role.COORDINATOR)),
           db: Session = Depends(get_db)) -> AccessRequestOut:
    r, user = _pending(db, coordinator, request_id)
    r.status, r.decided_by_id, r.decided_at = "REJECTED", coordinator.id, utcnow()
    r.decision_note = body.note if body else None
    db.add(AuditLog(actor_id=coordinator.id, action="ACCESS_REJECTED", target_type="user", target_id=user.id))
    commit(db)
    return _out(db, r)
