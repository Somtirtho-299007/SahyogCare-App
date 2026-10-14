"""Patients and their visits. See docs/WORKFLOW.md, "Patients and encounters".

One patient = one record. The ASHA registers each person she looks after once;
every visit, referral, prescription and medicine of that person stays under the
same record, so the history is never split across "random" entries.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.access import get_patient_for, get_referral_for, patient_scope
from app.db import get_db
from app.errors import ApiError
from app.models import AuditLog, Encounter, Medicine, Patient, User
from app.records import encounter_out, patient_record, record_death, register_rows, unique_health_id, vital_ranges
from app.rules import PATIENT_SIGN_IN_CODE_VALID_FOR, Role, triage_suggestion, validate_vitals
from app.schemas import (
    DeceasedIn,
    EncounterIn,
    EncounterOut,
    PatientCreatedOut,
    PatientIn,
    PatientOut,
    PatientRecordOut,
    PatientSignInCodeOut,
    PatientUpdateIn,
    RegisterRowOut,
    VitalRangeOut,
)
from app.security import current_user, require_roles
from app.timeutil import utcnow
from app.workflow import commit

router = APIRouter(prefix="/patients", tags=["patients"])
ranges_router = APIRouter(tags=["patients"])


@ranges_router.get("/vital-ranges", response_model=list[VitalRangeOut])
def get_vital_ranges() -> list[VitalRangeOut]:
    """Normal adult ranges shown beside every reading (placeholders for a doctor to confirm)."""
    return vital_ranges()


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
    # The person already made their own account on the Patient door (same mobile, same name):
    # take that record onto this ASHA's register instead of making a second one.
    own = db.scalar(select(Patient).where(Patient.self_registered.is_(True), Patient.phone == body.phone,
                                          func.lower(Patient.name) == body.name.lower()).with_for_update())
    if own is not None and duplicate is None:
        own.created_by_id, own.self_registered = user.id, False
        own.age, own.sex = body.age, body.sex or own.sex
        own.address = body.address or own.address
        own.email = body.email or own.email
        own.latitude, own.longitude = body.latitude or own.latitude, body.longitude or own.longitude
        db.add(AuditLog(actor_id=user.id, action="PATIENT_TAKEN_ON", target_type="patient", target_id=own.id))
        commit(db)
        return PatientCreatedOut(**PatientOut.model_validate(own).model_dump(), took_over_own_account=True)
    patient = Patient(
        name=body.name, age=body.age, sex=body.sex, phone=body.phone, abha_number=body.abha_number,
        email=body.email, language=body.language, address=body.address,
        latitude=body.latitude, longitude=body.longitude,
        consent_recorded_at=utcnow(), created_by_id=user.id, health_id=unique_health_id(db),
    )
    db.add(patient)
    db.flush()
    db.add(AuditLog(actor_id=user.id, action="PATIENT_CREATED", target_type="patient", target_id=patient.id))
    commit(db)
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


@router.get("/register", response_model=list[RegisterRowOut])
def register(
    q: str | None = Query(None, max_length=80, description="Name, phone, Health ID or village"),
    user: User = Depends(require_roles(Role.WORKER)),
    db: Session = Depends(get_db),
) -> list[RegisterRowOut]:
    """The ASHA's register of everyone she looks after."""
    return register_rows(db, user, q)


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Patient:
    return get_patient_for(db, user, patient_id)


@router.patch("/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: str, body: PatientUpdateIn, user: User = Depends(require_roles(Role.WORKER)),
                   db: Session = Depends(get_db)) -> Patient:
    patient = get_patient_for(db, user, patient_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None or field in ("email", "address", "latitude", "longitude"):
            setattr(patient, field, value)
    db.add(AuditLog(actor_id=user.id, action="PATIENT_UPDATED", target_type="patient", target_id=patient.id))
    commit(db)
    return patient


@router.get("/{patient_id}/record", response_model=PatientRecordOut)
def get_record(patient_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> PatientRecordOut:
    """The full history: conditions, prescriptions, care chart, vitals, every referral."""
    patient = get_patient_for(db, user, patient_id)
    out = patient_record(db, patient)
    db.commit()  # courses that just finished are saved as completed
    return out


@router.post("/{patient_id}/encounters", response_model=EncounterOut, status_code=201)
def create_encounter(
    patient_id: str,
    body: EncounterIn,
    user: User = Depends(require_roles(Role.WORKER, Role.DOCTOR, Role.FACILITY_STAFF)),
    db: Session = Depends(get_db),
) -> EncounterOut:
    """A visit or new readings. The ASHA records visits; the hospital may add readings after
    the checkup (e.g. everything back to normal), which then show on the referral."""
    patient = get_patient_for(db, user, patient_id)
    if patient.deceased_at is not None:
        raise ApiError(409, "PATIENT_DECEASED", "This patient has died; no new visits can be added.")
    if user.role != Role.WORKER and body.kind != "VITALS_UPDATE":
        raise ApiError(403, "FORBIDDEN", "The hospital can add new readings; visits are recorded by the ASHA.")
    if body.referral_id is not None:
        referral = get_referral_for(db, user, body.referral_id)
        if referral.patient_id != patient.id:
            raise ApiError(404, "NOT_FOUND", "Referral not found for this patient.")
    vitals = body.vitals.model_dump()
    problems = validate_vitals(vitals)
    if problems:
        raise ApiError(422, "VALIDATION_ERROR", "Some readings look wrong. Please check them.", {"fields": problems})

    enc = Encounter(patient_id=patient.id, created_by_id=user.id, reason=body.reason.strip(), triage=body.triage,
                    kind=body.kind, referral_id=body.referral_id, **vitals)
    enc.medicines = [Medicine(**m.model_dump()) for m in body.medicines]
    db.add(enc)
    db.flush()
    db.add(AuditLog(actor_id=user.id, action="ENCOUNTER_CREATED", target_type="encounter", target_id=enc.id))
    commit(db)
    hint = triage_suggestion(vitals) if body.triage != "EMERGENCY" and user.role == Role.WORKER else None
    return encounter_out(db, enc, hint)


@router.get("/{patient_id}/encounters", response_model=list[EncounterOut])
def list_encounters(patient_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[EncounterOut]:
    patient = get_patient_for(db, user, patient_id)
    encounters = db.scalars(
        select(Encounter)
        .where(Encounter.patient_id == patient.id)
        .options(selectinload(Encounter.medicines))
        .order_by(Encounter.created_at.desc())
    )
    return [encounter_out(db, e) for e in encounters]


@router.post("/{patient_id}/deceased", response_model=PatientOut)
def mark_deceased(patient_id: str, body: DeceasedIn,
                  user: User = Depends(require_roles(Role.WORKER, Role.DOCTOR, Role.FACILITY_STAFF, Role.COORDINATOR)),
                  db: Session = Depends(get_db)) -> Patient:
    """The patient died: stop every open referral at once, with cause and time of death."""
    patient = get_patient_for(db, user, patient_id, lock=True)
    if patient.deceased_at is not None:
        raise ApiError(409, "ALREADY_RECORDED", "The death of this patient is already recorded.")
    if body.died_at > utcnow():
        raise ApiError(422, "VALIDATION_ERROR", "The time of death cannot be in the future.",
                       {"fields": {"died_at": "In the future"}})
    record_death(db, patient, user, body.cause, body.died_at)
    commit(db)
    return patient


@router.post("/{patient_id}/sign-in-code", response_model=PatientSignInCodeOut)
def patient_sign_in_code(patient_id: str,
                         user: User = Depends(require_roles(Role.WORKER, Role.DOCTOR, Role.FACILITY_STAFF, Role.COORDINATOR)),
                         db: Session = Depends(get_db)) -> PatientSignInCodeOut:
    """A one-time code for the patient's own account, shown on the ASHA's phone.

    For places without the SMS service: the patient types their mobile number and this
    code on their own phone. Valid 15 minutes; any older code for that number stops working.
    """
    from app.routers.public import issue_patient_code, patient_key

    patient = get_patient_for(db, user, patient_id)
    code = issue_patient_code(db, patient_key(patient.phone, None), PATIENT_SIGN_IN_CODE_VALID_FOR)
    db.add(AuditLog(actor_id=user.id, action="PATIENT_SIGN_IN_CODE", target_type="patient", target_id=patient.id))
    db.commit()
    return PatientSignInCodeOut(code=code, phone=patient.phone, expires_at=utcnow() + PATIENT_SIGN_IN_CODE_VALID_FOR)
