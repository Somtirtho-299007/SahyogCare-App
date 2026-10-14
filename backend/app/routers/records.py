"""Medical history, prescriptions and the care chart.

The doctor writes the prescription on paper as usual; the ASHA enters it here (with a
photo of the paper) so the history is never lost. Doctors and the hospital can read
everything; doctors may also note conditions (e.g. "fatty liver" -> "resolved").
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.access import get_patient_for, get_referral_for
from app.db import get_db
from app.errors import ApiError
from app.models import AuditLog, CareItem, Condition, ConditionEvent, Patient, Prescription, User
from app.records import care_out, condition_out, end_care, local_today, prescription_out
from app.rules import CareStatus, Role
from app.schemas import (
    CareEndIn,
    CareItemIn,
    CareItemOut,
    ConditionIn,
    ConditionOut,
    ConditionUpdateIn,
    PrescriptionIn,
    PrescriptionOut,
)
from app.security import require_roles
from app.timeutil import utcnow
from app.workflow import commit

router = APIRouter(tags=["health record"])

ASHA = require_roles(Role.WORKER)
ASHA_OR_DOCTOR = require_roles(Role.WORKER, Role.DOCTOR)


def _alive(patient: Patient) -> None:
    if patient.deceased_at is not None:
        raise ApiError(409, "PATIENT_DECEASED", "This patient has died; the record is closed.")


def _care_item(patient: Patient, body: CareItemIn, user: User, prescription_id: str | None = None) -> CareItem:
    # A practice may have times too (e.g. "walk 20 minutes, morning and evening").
    return CareItem(
        patient_id=patient.id, prescription_id=prescription_id, kind=body.kind, category=body.category,
        name=body.name.strip(), dose=body.dose, quantity=body.quantity, timings=list(dict.fromkeys(body.timings)),
        food=body.food, start_date=body.start_date or local_today(), duration_days=body.duration_days,
        instructions=body.instructions, status=CareStatus.ACTIVE, created_by_id=user.id,
    )


# ---------- Conditions (medical history) ----------


@router.post("/patients/{patient_id}/conditions", response_model=ConditionOut, status_code=201)
def add_condition(patient_id: str, body: ConditionIn, user: User = Depends(ASHA_OR_DOCTOR),
                  db: Session = Depends(get_db)) -> ConditionOut:
    patient = get_patient_for(db, user, patient_id)
    now = utcnow()
    c = Condition(patient_id=patient.id, name=body.name.strip(), status=body.status, noted_on=body.noted_on,
                  created_by_id=user.id, created_at=now, updated_at=now)
    c.events.append(ConditionEvent(status=body.status, note=body.note, by_id=user.id, at=now))
    db.add(c)
    db.flush()
    db.add(AuditLog(actor_id=user.id, action="CONDITION_ADDED", target_type="condition", target_id=c.id))
    commit(db)
    return condition_out(c)


@router.patch("/conditions/{condition_id}", response_model=ConditionOut)
def update_condition(condition_id: str, body: ConditionUpdateIn, user: User = Depends(ASHA_OR_DOCTOR),
                     db: Session = Depends(get_db)) -> ConditionOut:
    """e.g. "Fatty liver" ACTIVE -> RESOLVED; the old status stays in the history."""
    c = db.get(Condition, condition_id)
    if c is None:
        raise ApiError(404, "NOT_FOUND", "Not found.")
    get_patient_for(db, user, c.patient_id)  # same scope as the patient
    now = utcnow()
    c.status, c.updated_at = body.status, now
    c.events.append(ConditionEvent(status=body.status, note=body.note, by_id=user.id, at=now))
    db.add(AuditLog(actor_id=user.id, action="CONDITION_UPDATED", target_type="condition", target_id=c.id))
    commit(db)
    return condition_out(c)


# ---------- Prescriptions ----------


@router.post("/patients/{patient_id}/prescriptions", response_model=PrescriptionOut, status_code=201)
def add_prescription(patient_id: str, body: PrescriptionIn, user: User = Depends(ASHA),
                     db: Session = Depends(get_db)) -> PrescriptionOut:
    """The ASHA enters the doctor's paper prescription; its medicines go onto the care chart."""
    patient = get_patient_for(db, user, patient_id)
    _alive(patient)
    if body.referral_id is not None:
        referral = get_referral_for(db, user, body.referral_id)
        if referral.patient_id != patient.id:
            raise ApiError(404, "NOT_FOUND", "Referral not found for this patient.")
    p = Prescription(patient_id=patient.id, referral_id=body.referral_id, doctor_name=body.doctor_name,
                     facility_name=body.facility_name, prescribed_on=body.prescribed_on or local_today(),
                     diagnosis=body.diagnosis, notes=body.notes, recorded_by_id=user.id)
    db.add(p)
    db.flush()
    for item in body.items:
        start = item.start_date or p.prescribed_on
        db.add(_care_item(patient, item.model_copy(update={"start_date": start}), user, p.id))
    db.add(AuditLog(actor_id=user.id, action="PRESCRIPTION_ADDED", target_type="prescription", target_id=p.id))
    commit(db)
    return prescription_out(db, p)


# ---------- Care chart: medicines and practices ----------


@router.post("/patients/{patient_id}/care-items", response_model=CareItemOut, status_code=201)
def add_care_item(patient_id: str, body: CareItemIn, user: User = Depends(ASHA),
                  db: Session = Depends(get_db)) -> CareItemOut:
    patient = get_patient_for(db, user, patient_id)
    _alive(patient)
    item = _care_item(patient, body, user)
    db.add(item)
    db.flush()
    db.add(AuditLog(actor_id=user.id, action="CARE_ITEM_ADDED", target_type="care_item", target_id=item.id))
    commit(db)
    return care_out(item)


@router.post("/care-items/{item_id}/end", response_model=CareItemOut)
def finish_care_item(item_id: str, body: CareEndIn, user: User = Depends(ASHA),
                     db: Session = Depends(get_db)) -> CareItemOut:
    """Course done (or stopped): it leaves the chart and stays in the history."""
    item = db.get(CareItem, item_id)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "Not found.")
    get_patient_for(db, user, item.patient_id)
    if item.status != CareStatus.ACTIVE:
        raise ApiError(409, "ALREADY_ENDED", "This item is already finished.")
    end_care(item, body.status, body.reason)
    db.add(AuditLog(actor_id=user.id, action=f"CARE_ITEM_{body.status}", target_type="care_item", target_id=item.id))
    commit(db)
    return care_out(item)
