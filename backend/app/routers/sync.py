"""Offline sync. See docs/WORKFLOW.md, "Offline and low bandwidth".

A phone that was offline keeps a queue of actions, each with its own
idempotency key, and uploads them with POST /sync/batch when the network
returns. Every action runs through exactly the same rules as the normal
endpoints. Re-sending an action that already succeeded returns the first
result instead of doing it twice.

Actions in one batch can refer to things created earlier in the queue with
"$ref:<idempotency_key>", e.g. a referral for a patient created offline:
  {"idempotency_key": "p1", "type": "CREATE_PATIENT", "payload": {...}}
  {"idempotency_key": "e1", "type": "CREATE_ENCOUNTER", "payload": {"patient_id": "$ref:p1", ...}}
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import referral_scope
from app.db import get_db
from app.errors import ApiError
from app.models import IdempotencyKey, Notification, Referral, User
from app.routers import ambulance, followups, patients, referrals
from app.rules import Role
from app.schemas import (
    EncounterIn,
    NoteIn,
    NotificationOut,
    OutcomeIn,
    PassVerifyIn,
    PatientIn,
    ReferralIn,
    AmbulanceDispatchIn,
    AmbulanceRequestIn,
    ReferralOut,
    RejectIn,
    RerouteIn,
)
from app.security import current_user
from app.timeutil import as_utc, utcnow
from app.workflow import referral_out

router = APIRouter(prefix="/sync", tags=["sync"])

OpType = Literal[
    "CREATE_PATIENT", "CREATE_ENCOUNTER", "CREATE_REFERRAL", "SCAN_PASS",
    "ACCEPT", "REJECT", "ARRIVAL", "CONSULTATION", "OUTCOME", "CLOSE", "ESCALATE",
    "COMPLETE_FOLLOW_UP", "MISS_FOLLOW_UP", "SEND_FOLLOW_UP",
    "REROUTE", "REQUEST_AMBULANCE", "DISPATCH_AMBULANCE", "AMBULANCE_PICKED_UP",
]


class Operation(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=80)
    type: OpType
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchIn(BaseModel):
    operations: list[Operation] = Field(min_length=1, max_length=100)


class OpError(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class OpResult(BaseModel):
    idempotency_key: str
    status: Literal["ok", "error"]
    replayed: bool = False  # True when this action had already been applied earlier
    result: dict | None = None
    error: OpError | None = None


class BatchOut(BaseModel):
    results: list[OpResult]


class ChangesOut(BaseModel):
    cursor: datetime  # send this as `since` next time
    referrals: list[ReferralOut]
    notifications: list[NotificationOut]


def _pop(payload: dict, key: str) -> str:
    value = payload.pop(key, None)
    if not isinstance(value, str) or not value:
        raise ApiError(422, "VALIDATION_ERROR", f"{key} is required.", {"fields": {key: "Required"}})
    return value


def _note(p: dict) -> NoteIn:
    return NoteIn(**p)


# type -> (roles allowed, handler(payload, user, db) -> pydantic model)
HANDLERS: dict[str, tuple[set[str] | None, Callable[[dict, User, Session], BaseModel]]] = {
    "CREATE_PATIENT": ({Role.WORKER}, lambda p, u, db: patients.create_patient(PatientIn(**p), u, db)),
    "CREATE_ENCOUNTER": ({Role.WORKER}, lambda p, u, db: patients.create_encounter(
        _pop(p, "patient_id"), EncounterIn(**p), u, db)),
    "CREATE_REFERRAL": ({Role.WORKER}, lambda p, u, db: referrals.create_referral(ReferralIn(**p), None, u, db)),
    "SCAN_PASS": ({Role.FACILITY_STAFF}, lambda p, u, db: referrals.verify_pass(PassVerifyIn(**p), u, db)),
    # Status changes check roles themselves through the state machine.
    "ACCEPT": (None, lambda p, u, db: referrals.accept(_pop(p, "referral_id"), _note(p), u, db)),
    "REJECT": (None, lambda p, u, db: referrals.reject(_pop(p, "referral_id"), RejectIn(**p), u, db)),
    "ARRIVAL": (None, lambda p, u, db: referrals.arrival(_pop(p, "referral_id"), _note(p), u, db)),
    "CONSULTATION": (None, lambda p, u, db: referrals.consultation(_pop(p, "referral_id"), _note(p), u, db)),
    "OUTCOME": (None, lambda p, u, db: referrals.outcome(_pop(p, "referral_id"), OutcomeIn(**p), u, db)),
    "CLOSE": (None, lambda p, u, db: referrals.close(_pop(p, "referral_id"), _note(p), u, db)),
    "ESCALATE": (None, lambda p, u, db: referrals.escalate(_pop(p, "referral_id"), _note(p), u, db)),
    "SEND_FOLLOW_UP": ({Role.WORKER}, lambda p, u, db: followups.sent(_pop(p, "follow_up_id"), _note(p), u, db)),
    "COMPLETE_FOLLOW_UP": ({Role.FACILITY_STAFF, Role.DOCTOR}, lambda p, u, db: followups.complete(
        _pop(p, "follow_up_id"), _note(p), u, db)),
    "MISS_FOLLOW_UP": ({Role.WORKER}, lambda p, u, db: followups.miss(_pop(p, "follow_up_id"), _note(p), u, db)),
    "REROUTE": ({Role.WORKER, Role.COORDINATOR}, lambda p, u, db: referrals.reroute(
        _pop(p, "referral_id"), RerouteIn(**p), u, db)),
    "REQUEST_AMBULANCE": ({Role.WORKER, Role.COORDINATOR}, lambda p, u, db: ambulance.request_ambulance(
        _pop(p, "referral_id"), AmbulanceRequestIn(**p), u, db)),
    "DISPATCH_AMBULANCE": ({Role.FACILITY_STAFF}, lambda p, u, db: ambulance.dispatch(
        _pop(p, "referral_id"), AmbulanceDispatchIn(**p), u, db)),
    "AMBULANCE_PICKED_UP": ({Role.FACILITY_STAFF, Role.WORKER}, lambda p, u, db: ambulance.picked_up(
        _pop(p, "referral_id"), u, db)),
}


def _resolve(value: Any, ids: dict[str, str], db: Session, user: User) -> Any:
    """Replace "$ref:<key>" with the id created by that earlier action."""
    if isinstance(value, dict):
        return {k: _resolve(v, ids, db, user) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, ids, db, user) for v in value]
    if isinstance(value, str) and value.startswith("$ref:"):
        key = value[5:]
        if key not in ids:
            stored = db.get(IdempotencyKey, _scoped(user, key))
            if stored is None or not (stored.response.get("result") or {}).get("id"):
                raise ApiError(422, "UNKNOWN_REFERENCE", f"No earlier action with key {key} succeeded.")
            ids[key] = stored.response["result"]["id"]
        return ids[key]
    return value


def _scoped(user: User, key: str) -> str:
    return f"{user.id}:sync:{key}"


def _run(op: Operation, user: User, db: Session, ids: dict[str, str]) -> OpResult:
    stored = db.get(IdempotencyKey, _scoped(user, op.idempotency_key))
    if stored is not None:
        result = stored.response.get("result") or {}
        if result.get("id"):
            ids[op.idempotency_key] = result["id"]
        return OpResult(idempotency_key=op.idempotency_key, status="ok", replayed=True, result=result)

    roles, handler = HANDLERS[op.type]
    try:
        if roles is not None and user.role not in roles:
            raise ApiError(403, "FORBIDDEN", "Your role cannot do this.")
        payload = _resolve(dict(op.payload), ids, db, user)
        model = handler(payload, user, db)
    except ApiError as exc:
        db.rollback()
        code = exc.code
        if code == "INVALID_STATE_TRANSITION":
            # Something changed on the server while the phone was offline.
            code = "SYNC_CONFLICT"
        return OpResult(idempotency_key=op.idempotency_key, status="error",
                        error=OpError(code=code, message=exc.message, details=exc.details))
    except ValidationError as exc:
        db.rollback()
        fields = {".".join(str(p) for p in e["loc"]) or "payload": e["msg"] for e in exc.errors()}
        return OpResult(idempotency_key=op.idempotency_key, status="error",
                        error=OpError(code="VALIDATION_ERROR", message="Some fields are missing or invalid.",
                                      details={"fields": fields}))

    result = model.model_dump(mode="json")
    if "referral" in result and "id" not in result:  # SCAN_PASS returns {referral, already_recorded}
        result["id"] = result["referral"]["id"]
    if result.get("id"):
        ids[op.idempotency_key] = result["id"]
    db.add(IdempotencyKey(key=_scoped(user, op.idempotency_key), user_id=user.id,
                          response={"type": op.type, "result": result}))
    db.commit()
    return OpResult(idempotency_key=op.idempotency_key, status="ok", result=result)


@router.post("/batch", response_model=BatchOut)
def batch(body: BatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> BatchOut:
    """Apply queued offline actions in order. One failure does not stop the others."""
    ids: dict[str, str] = {}
    return BatchOut(results=[_run(op, user, db, ids) for op in body.operations])


@router.get("/changes", response_model=ChangesOut)
def changes(
    since: datetime | None = Query(None, description="The cursor from the previous call; omit for everything"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ChangesOut:
    """What changed for this user since the last sync: referrals in scope and their own alerts."""
    cursor = utcnow()
    since_utc = as_utc(since) if since else None
    refs = [r for r in db.scalars(select(Referral).where(referral_scope(user)))
            if since_utc is None or as_utc(r.updated_at) > since_utc]
    notes = [n for n in db.scalars(select(Notification).where(Notification.user_id == user.id))
             if since_utc is None or as_utc(n.created_at) > since_utc]
    refs.sort(key=lambda r: as_utc(r.updated_at))
    return ChangesOut(
        cursor=cursor,
        referrals=[referral_out(db, r) for r in refs[:500]],
        notifications=[NotificationOut.model_validate(n) for n in notes[-200:]],
    )
