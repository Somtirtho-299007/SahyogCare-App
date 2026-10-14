"""The district office's own door: it enters with its area's permanent passphrase.

There are no group invite codes any more. Everyone else joins one way only:
verify email/phone -> ask to join -> the district office approves -> a personal code
(app/staffcode.py) appears on their own dashboard -> every later login asks for it.
The district office itself enters once with the passphrase, then also gets a personal code.
"""

import hmac

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import offices
from app.config import settings
from app.db import get_db
from app.errors import ApiError
from app.models import AccessRequest, AuditLog, Notification, User
from app.ratelimit import RateLimiter
from app.rules import OFFICE_ATTEMPTS_PER_10_MIN, Role
from app.schemas import UserOut
from app.security import current_user_any
from app.timeutil import utcnow
from app.workflow import commit

router = APIRouter(prefix="/office", tags=["district office"])
office_limiter = RateLimiter(OFFICE_ATTEMPTS_PER_10_MIN, window_seconds=600)


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


@router.post("/join", response_model=UserOut)
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
                            message=f"{user.name} ({user.contact}) joined the {area} office with the passphrase."))
    commit(db)
    return UserOut.model_validate(user)
