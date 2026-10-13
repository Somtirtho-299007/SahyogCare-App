"""Invite codes: the district office hands out secret codes instead of approving people one by one.

- Coordinator makes a code for a role: ASHA (whole district), hospital staff or
  doctor (one hospital), or another coordinator (single use, max 7 days).
- A person logs in with their own email, enters the code, and gets that role at
  once. Wrong guesses are limited, codes can expire, have a use limit, and can be
  revoked; everyone who joined is listed and can be switched off.
- The very first coordinator comes from SAHYOG_COORDINATOR_EMAILS (no code needed).
"""

import hmac
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import offices
from app.db import get_db
from app.errors import ApiError
from app.models import AccessRequest, AuditLog, Facility, InviteCode, Notification, User
from app.ratelimit import RateLimiter
from app.config import settings
from app.rules import (
    COORDINATOR_INVITE_MAX_DAYS,
    INVITE_ATTEMPTS_PER_10_MIN,
    OFFICE_ATTEMPTS_PER_10_MIN,
    Role,
    new_invite_code,
)
from app.schemas import UserOut
from app.security import current_user_any, require_roles
from app.timeutil import as_utc, utcnow
from app.workflow import commit

router = APIRouter(prefix="/invite-codes", tags=["invite codes"])
redeem_limiter = RateLimiter(INVITE_ATTEMPTS_PER_10_MIN, window_seconds=600)
office_limiter = RateLimiter(OFFICE_ATTEMPTS_PER_10_MIN, window_seconds=600)
HOSPITAL_ROLES = {Role.FACILITY_STAFF, Role.DOCTOR}


class InviteIn(BaseModel):
    role: Literal["WORKER", "FACILITY_STAFF", "DOCTOR", "COORDINATOR"]
    facility_id: str | None = None  # required for hospital staff and doctors
    label: str | None = Field(None, max_length=120)
    max_uses: int | None = Field(None, ge=1, le=1000)
    expires_in_days: int | None = Field(30, ge=1, le=365)


class InviteOut(BaseModel):
    id: str
    code: str
    role: str
    facility_id: str | None
    facility_name: str | None
    label: str | None
    max_uses: int | None
    uses: int
    expires_at: datetime | None
    revoked: bool
    usable: bool
    created_at: datetime


class RedeemIn(BaseModel):
    code: str = Field(min_length=6, max_length=24)
    name: str = Field(min_length=1, max_length=120)


def _usable(c: InviteCode, now: datetime) -> bool:
    return (c.revoked_at is None and (c.expires_at is None or as_utc(c.expires_at) > now)
            and (c.max_uses is None or c.uses < c.max_uses))


def _out(db: Session, c: InviteCode) -> InviteOut:
    facility = db.get(Facility, c.facility_id) if c.facility_id else None
    return InviteOut(
        id=c.id, code=c.code, role=c.role, facility_id=c.facility_id,
        facility_name=facility.name if facility else None, label=c.label, max_uses=c.max_uses, uses=c.uses,
        expires_at=as_utc(c.expires_at), revoked=c.revoked_at is not None, usable=_usable(c, utcnow()),
        created_at=as_utc(c.created_at),
    )


@router.post("", response_model=InviteOut, status_code=201)
def create_code(body: InviteIn, coordinator: User = Depends(require_roles(Role.COORDINATOR)),
                db: Session = Depends(get_db)) -> InviteOut:
    place = coordinator.district
    if body.role in HOSPITAL_ROLES:
        facility = db.get(Facility, body.facility_id) if body.facility_id else None
        if facility is None or not facility.active or facility.district.lower() != coordinator.district.lower():
            raise ApiError(422, "VALIDATION_ERROR", "Choose a hospital in your district for this code.",
                           {"fields": {"facility_id": "Required"}})
        place = facility.name
    elif body.facility_id is not None:
        raise ApiError(422, "VALIDATION_ERROR", "Only hospital staff and doctor codes belong to a hospital.",
                       {"fields": {"facility_id": "Not allowed for this role"}})

    max_uses, days = body.max_uses, body.expires_in_days
    if body.role == Role.COORDINATOR:
        # Joining as district office is powerful: one person, one week at most.
        max_uses, days = 1, min(days or COORDINATOR_INVITE_MAX_DAYS, COORDINATOR_INVITE_MAX_DAYS)

    code = new_invite_code(body.role, place)
    while db.scalar(select(InviteCode.id).where(InviteCode.code == code)):
        code = new_invite_code(body.role, place)
    invite = InviteCode(code=code, role=body.role, district=coordinator.district, facility_id=body.facility_id,
                        label=body.label, max_uses=max_uses, created_by_id=coordinator.id,
                        expires_at=utcnow() + timedelta(days=days) if days else None)
    db.add(invite)
    db.flush()
    db.add(AuditLog(actor_id=coordinator.id, action="INVITE_CREATED", target_type="invite_code", target_id=invite.id))
    commit(db)
    return _out(db, invite)


@router.get("", response_model=list[InviteOut])
def list_codes(coordinator: User = Depends(require_roles(Role.COORDINATOR)),
               db: Session = Depends(get_db)) -> list[InviteOut]:
    codes = db.scalars(select(InviteCode).where(func.lower(InviteCode.district) == coordinator.district.lower())
                       .order_by(InviteCode.created_at.desc()))
    return [_out(db, c) for c in codes]


@router.post("/{invite_id}/revoke", response_model=InviteOut)
def revoke(invite_id: str, coordinator: User = Depends(require_roles(Role.COORDINATOR)),
           db: Session = Depends(get_db)) -> InviteOut:
    invite = db.get(InviteCode, invite_id)
    if invite is None or invite.district.lower() != coordinator.district.lower():
        raise ApiError(404, "NOT_FOUND", "Not found.")
    invite.revoked_at = invite.revoked_at or utcnow()
    db.add(AuditLog(actor_id=coordinator.id, action="INVITE_REVOKED", target_type="invite_code", target_id=invite.id))
    commit(db)
    return _out(db, invite)


@router.post("/redeem", response_model=UserOut)
def redeem(body: RedeemIn, user: User = Depends(current_user_any), db: Session = Depends(get_db)) -> UserOut:
    """Join with a code: the logged-in person gets the code's role (and hospital) at once."""
    if user.approved:
        raise ApiError(409, "ALREADY_APPROVED", "Your account already has a role.")
    redeem_limiter.check(user.id)
    invite = db.scalar(select(InviteCode).where(InviteCode.code == body.code.strip().upper()).with_for_update())
    now = utcnow()
    if invite is None or not _usable(invite, now):
        # Same answer for wrong, expired, used-up or revoked codes.
        raise ApiError(400, "INVITE_INVALID", "This code is not valid. Check it with your district office.")

    invite.uses += 1
    user.role, user.facility_id, user.name, user.approved = invite.role, invite.facility_id, body.name.strip(), True
    user.district = invite.district
    request = AccessRequest(user_id=user.id, requested_role=invite.role, facility_id=invite.facility_id,
                            name=user.name, status="APPROVED", decided_at=now,
                            decision_note=f"Joined with invite code {invite.code[:7]}…")
    db.add(request)
    db.add(AuditLog(actor_id=user.id, action="INVITE_REDEEMED", target_type="invite_code", target_id=invite.id))
    commit(db)
    return UserOut.model_validate(user)


def _office_passphrase_ok(area: str, passphrase: str) -> bool:
    """The built-in passphrase (app/offices.py), or one set on the server, if any."""
    stored = offices.stored_hash(area)
    built_in = stored is not None and offices.matches(passphrase, stored)
    extra = settings.office_passphrase(area)
    on_server = extra is not None and hmac.compare_digest(passphrase.strip().encode(), extra.encode())
    return built_in or on_server


class OfficeJoinIn(BaseModel):
    district: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    passphrase: str = Field(min_length=1, max_length=200)


@router.post("/office", response_model=UserOut)
def join_as_office(body: OfficeJoinIn, user: User = Depends(current_user_any),
                   db: Session = Depends(get_db)) -> UserOut:
    """District office enters with the fixed passphrase only it knows (set on the server)."""
    if user.approved:
        raise ApiError(409, "ALREADY_APPROVED", "Your account already has a role.")
    office_limiter.check(user.id)
    area = settings.canonical_district(body.district)
    # Same answer for an unknown area, an area without a passphrase, and a wrong passphrase.
    if not area or not _office_passphrase_ok(area, body.passphrase):
        raise ApiError(400, "PASSPHRASE_INVALID", "This passphrase is not right for this area.")

    now = utcnow()
    user.role, user.facility_id, user.name, user.approved, user.district = (
        Role.COORDINATOR, None, body.name.strip(), True, area)
    db.add(AccessRequest(user_id=user.id, requested_role=Role.COORDINATOR, name=user.name, status="APPROVED",
                         decided_at=now, decision_note="Joined with the district office passphrase"))
    db.add(AuditLog(actor_id=user.id, action="OFFICE_PASSPHRASE_USED", target_type="user", target_id=user.id))
    # Every existing coordinator of the area learns that someone joined this way.
    others = db.scalars(select(User.id).where(User.role == Role.COORDINATOR, User.id != user.id,
                                              func.lower(User.district) == area.lower(), User.is_active.is_(True)))
    for cid in others:
        db.add(Notification(user_id=cid, referral_id=None, kind="OFFICE_JOINED",
                            message=f"{user.name} ({user.email}) joined the {area} office with the passphrase."))
    commit(db)
    return UserOut.model_validate(user)
