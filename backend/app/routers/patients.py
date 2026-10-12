"""Patients and encounters (visits). See docs/WORKFLOW.md, "Patients and encounters"."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.access import get_patient_for, patient_scope
from app.db import get_db
from app.errors import ApiError
from app.models import AuditLog, Encounter, Medicine, Patient, User
from app.rules import Role, triage_suggestion, validate_vitals
from app.schemas import EncounterIn, EncounterOut, MedicineOut, PatientCreatedOut, PatientIn, PatientOut, Vitals
from app.security import current_user, require_roles
from app.timeutil import as_utc, utcnow

router = APIRouter(prefix="/patients", tags=["patients"])


def _encounter_out(enc: Encounter, suggestion: str | None = None) -> EncounterOut:
    return EncounterOut(
        id=enc.id,
        patient_id=enc.patient_id,
        reason=enc.reason,
        triage=enc.triage,
        vitals=Vitals(**{f: getattr(enc, f) for f in Vitals.model_fields}),
        medicines=[MedicineOut.model_validate(m) for m in enc.medicines],
        created_at=as_utc(enc.created_at),
        triage_suggestion=suggestion,
    )


@router.post("", response_model=PatientCreatedOut, status_code=201)
def create_patient(
    body: PatientIn, user: User = Depends(require_roles(Role.WORKER)), db: Session = Depends(get_db)
) -> PatientCreatedOut:
    if not body.consent_given:
        raise ApiError(422, "CONSENT_REQUIRED", "The patient's consent must be recorded before saving their details.")

    duplicate = db.scalar(
        select(Patient.id).where(
            Patient.created_by_id == user.id,
            Patient.phone == body.phone,
            func.lower(Patient.name) == body.name.lower(),
        )
    )
    patient = Patient(
        name=body.name,
        age=body.age,
        sex=body.sex,
        phone=body.phone,
        abha_number=body.abha_number,
        consent_recorded_at=utcnow(),
        created_by_id=user.id,
    )
    db.add(patient)
    db.flush()
    db.add(AuditLog(actor_id=user.id, action="PATIENT_CREATED", target_type="patient", target_id=patient.id))
    db.commit()
    return PatientCreatedOut(**PatientOut.model_validate(patient).model_dump(), possible_duplicate_of=duplicate)


@router.get("", response_model=list[PatientOut])
def list_patients(
    q: str | None = Query(None, max_length=80, description="Matches name or phone"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[Patient]:
    stmt = select(Patient).where(patient_scope(user)).order_by(Patient.created_at.desc()).limit(50)
    if q:
        stmt = stmt.where(or_(Patient.name.ilike(f"%{q}%"), Patient.phone.contains(q)))
    return list(db.scalars(stmt))


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Patient:
    return get_patient_for(db, user, patient_id)


@router.post("/{patient_id}/encounters", response_model=EncounterOut, status_code=201)
def create_encounter(
    patient_id: str,
    body: EncounterIn,
    user: User = Depends(require_roles(Role.WORKER)),
    db: Session = Depends(get_db),
) -> EncounterOut:
    patient = get_patient_for(db, user, patient_id)
    vitals = body.vitals.model_dump()
    problems = validate_vitals(vitals)
    if problems:
        raise ApiError(422, "VALIDATION_ERROR", "Some readings look wrong. Please check them.", {"fields": problems})

    enc = Encounter(patient_id=patient.id, created_by_id=user.id, reason=body.reason.strip(), triage=body.triage, **vitals)
    enc.medicines = [Medicine(**m.model_dump()) for m in body.medicines]
    db.add(enc)
    db.flush()
    db.add(AuditLog(actor_id=user.id, action="ENCOUNTER_CREATED", target_type="encounter", target_id=enc.id))
    db.commit()
    hint = triage_suggestion(vitals) if body.triage != "EMERGENCY" else None
    return _encounter_out(enc, hint)


@router.get("/{patient_id}/encounters", response_model=list[EncounterOut])
def list_encounters(patient_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[EncounterOut]:
    patient = get_patient_for(db, user, patient_id)
    encounters = db.scalars(
        select(Encounter)
        .where(Encounter.patient_id == patient.id)
        .options(selectinload(Encounter.medicines))
        .order_by(Encounter.created_at.desc())
    )
    return [_encounter_out(e) for e in encounters]
