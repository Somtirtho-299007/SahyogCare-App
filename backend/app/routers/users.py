"""User accounts. The coordinator (district office) adds and manages every user.

The first coordinators come from SAHYOG_COORDINATOR_EMAILS when the server starts
(see app/accounts.py). They then add ASHAs, hospital staff and doctors here, using
each person's real email address; those people log in with a code sent to it.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import staffcode
from app.db import get_db
from app.errors import ApiError
from app.models import AuditLog, Facility, Notification, User
from app.rules import Role
from app.schemas import Email, UserOut
from app.security import require_roles
from app.workflow import commit

router = APIRouter(prefix="/users", tags=["users"])

RoleName = Literal["WORKER", "FACILITY_STAFF", "DOCTOR", "COORDINATOR"]
HOSPITAL_ROLES = {Role.FACILITY_STAFF, Role.DOCTOR}


class UserIn(BaseModel):
    email: Email
    name: str = Field(min_length=1, max_length=120)
    role: RoleName
    # Required for hospital staff and doctors: the hospital they work at.
    facility_id: str | None = None


class UserUpdateIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    is_active: bool | None = None
    facility_id: str | None = None


class UserListOut(UserOut):
    is_active: bool
    has_code: bool = False  # has a personal code (never the code itself)


def _listed(user: User) -> UserListOut:
    return UserListOut(**UserOut.model_validate(user).model_dump(), is_active=user.is_active,
                       has_code=bool(user.code_hash))


def _check_facility(db: Session, coordinator: User, role: str, facility_id: str | None) -> None:
    if role in HOSPITAL_ROLES:
        facility = db.get(Facility, facility_id) if facility_id else None
        if facility is None or not facility.active or facility.district.lower() != coordinator.district.lower():
            raise ApiError(422, "VALIDATION_ERROR", "Choose a hospital in your district for this person.",
                           {"fields": {"facility_id": "Required"}})
    elif facility_id is not None:
        raise ApiError(422, "VALIDATION_ERROR", "Only hospital staff and doctors belong to a hospital.",
                       {"fields": {"facility_id": "Not allowed for this role"}})


def _in_district(db: Session, coordinator: User, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.district.lower() != coordinator.district.lower():
        raise ApiError(404, "NOT_FOUND", "Not found.")
    return user


@router.get("", response_model=list[UserListOut])
def list_users(coordinator: User = Depends(require_roles(Role.COORDINATOR)),
               db: Session = Depends(get_db)) -> list[UserListOut]:
    users = db.scalars(select(User).where(func.lower(User.district) == coordinator.district.lower())
                       .order_by(User.role, User.name))
    return [_listed(u) for u in users]


@router.post("", response_model=UserListOut, status_code=201)
def add_user(body: UserIn, coordinator: User = Depends(require_roles(Role.COORDINATOR)),
             db: Session = Depends(get_db)) -> UserListOut:
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise ApiError(409, "DUPLICATE_USER", "This email already has an account.")
    _check_facility(db, coordinator, body.role, body.facility_id)
    user = User(email=body.email, name=body.name.strip(), role=body.role, facility_id=body.facility_id,
                district=coordinator.district)
    db.add(user)
    db.flush()
    db.add(AuditLog(actor_id=coordinator.id, action="USER_CREATED", target_type="user", target_id=user.id))
    commit(db)
    return _listed(user)


@router.patch("/{user_id}", response_model=UserListOut)
def update_user(user_id: str, body: UserUpdateIn, coordinator: User = Depends(require_roles(Role.COORDINATOR)),
                db: Session = Depends(get_db)) -> UserListOut:
    user = _in_district(db, coordinator, user_id)
    if body.is_active is False and user.id == coordinator.id:
        raise ApiError(422, "VALIDATION_ERROR", "You cannot switch off your own account.")
    if body.facility_id is not None:
        _check_facility(db, coordinator, user.role, body.facility_id)
        user.facility_id = body.facility_id
    if body.name is not None:
        user.name = body.name.strip()
    if body.is_active is not None:
        user.is_active = body.is_active
    db.add(AuditLog(actor_id=coordinator.id, action="USER_UPDATED", target_type="user", target_id=user.id))
    commit(db)
    return _listed(user)


@router.post("/{user_id}/reset-code", response_model=UserListOut)
def reset_code(user_id: str, coordinator: User = Depends(require_roles(Role.COORDINATOR)),
               db: Session = Depends(get_db)) -> UserListOut:
    """Forgotten or leaked personal code: the old one stops working at once, and a new one
    is shown on the person's own dashboard the next time they log in."""
    user = _in_district(db, coordinator, user_id)
    staffcode.clear(user)
    db.add(Notification(user_id=user.id, referral_id=None, kind="CODE_RESET",
                        message="Your personal code was reset by the district office. A new one is shown when you log in."))
    db.add(AuditLog(actor_id=coordinator.id, action="PERSONAL_CODE_RESET", target_type="user", target_id=user.id))
    commit(db)
    return _listed(user)
