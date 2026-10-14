"""The patient's health record: vitals with normal ranges, conditions, prescriptions,
the care chart (medicines and practices), and recording a death.

One patient = one record. Every referral, visit, prescription and medicine of that
patient hangs off it, so the history is complete even if paper reports are lost.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AuditLog,
    CareItem,
    Condition,
    Encounter,
    Facility,
    FollowUp,
    Patient,
    Prescription,
    Referral,
    User,
)
from app.rules import (
    LOCAL_UTC_OFFSET,
    NORMAL_RANGES,
    CareStatus,
    Status,
    is_open,
    new_health_id,
    vital_flag,
)
from app.schemas import (
    CareItemOut,
    ConditionEventOut,
    ConditionOut,
    EncounterOut,
    MedicineOut,
    PatientOut,
    PatientRecordOut,
    PrescriptionOut,
    ReferralBrief,
    RegisterRowOut,
    VitalRangeOut,
    Vitals,
)
from app.timeutil import as_utc, utcnow

VITAL_FIELDS = list(Vitals.model_fields)
FINISHED_CARE_SHOWN = 20  # recently finished care items kept visible on the record


def local_today(now: datetime | None = None) -> date:
    return ((now or utcnow()) + LOCAL_UTC_OFFSET).date()


def unique_health_id(db: Session) -> str:
    code = new_health_id()
    while db.scalar(select(Patient.id).where(Patient.health_id == code)):
        code = new_health_id()
    return code


# ---------- Vitals ----------


def vital_ranges() -> list[VitalRangeOut]:
    return [VitalRangeOut(field=f, low=low, high=high, label=label) for f, (low, high, label) in NORMAL_RANGES.items()]


def flags_for(vitals: dict[str, float | None]) -> dict[str, str]:
    return {f: flag for f, v in vitals.items() if (flag := vital_flag(f, v)) is not None}


def encounter_vitals(enc: Encounter) -> dict[str, float | None]:
    return {f: getattr(enc, f) for f in VITAL_FIELDS}


def has_vitals(enc: Encounter) -> bool:
    return any(v is not None for v in encounter_vitals(enc).values())


def encounter_out(db: Session, enc: Encounter, suggestion: str | None = None) -> EncounterOut:
    vitals = encounter_vitals(enc)
    author = db.get(User, enc.created_by_id)
    return EncounterOut(
        id=enc.id, patient_id=enc.patient_id, reason=enc.reason, triage=enc.triage, vitals=Vitals(**vitals),
        medicines=[MedicineOut.model_validate(m) for m in enc.medicines], created_at=as_utc(enc.created_at),
        triage_suggestion=suggestion, kind=enc.kind, referral_id=enc.referral_id, flags=flags_for(vitals),
        recorded_by_role=author.role if author else None,
    )


def latest_vitals(db: Session, patient_id: str) -> Encounter | None:
    """The newest visit of this patient that has at least one reading."""
    for enc in db.scalars(select(Encounter).where(Encounter.patient_id == patient_id)
                          .order_by(Encounter.created_at.desc()).limit(30)):
        if has_vitals(enc):
            return enc
    return None


# ---------- Care chart ----------


def end_date(item: CareItem) -> date | None:
    return item.start_date + timedelta(days=item.duration_days - 1) if item.duration_days else None


def care_out(item: CareItem, today: date | None = None) -> CareItemOut:
    today = today or local_today()
    last = end_date(item)
    days_left = max((last - today).days + 1, 0) if last and item.status == CareStatus.ACTIVE else None
    return CareItemOut(
        id=item.id, kind=item.kind, category=item.category, name=item.name, dose=item.dose, quantity=item.quantity,
        timings=list(item.timings or []), food=item.food, start_date=item.start_date, end_date=last,
        duration_days=item.duration_days, days_left=days_left, instructions=item.instructions, status=item.status,
        ended_at=as_utc(item.ended_at), end_reason=item.end_reason, prescription_id=item.prescription_id,
    )


def complete_finished_courses(db: Session, patient_id: str | None = None, today: date | None = None) -> int:
    """A course whose last day has passed is completed automatically (and leaves the chart)."""
    today = today or local_today()
    stmt = select(CareItem).where(CareItem.status == CareStatus.ACTIVE, CareItem.duration_days.is_not(None))
    if patient_id:
        stmt = stmt.where(CareItem.patient_id == patient_id)
    done = 0
    for item in db.scalars(stmt):
        if end_date(item) < today:
            item.status, item.ended_at, item.end_reason = CareStatus.COMPLETED, utcnow(), "Course finished"
            done += 1
    return done


def end_care(item: CareItem, status: str, reason: str | None) -> None:
    item.status, item.ended_at = status, utcnow()
    item.end_reason = reason or ("Marked done" if status == CareStatus.COMPLETED else "Stopped")


# ---------- Conditions and prescriptions ----------


def condition_out(c: Condition) -> ConditionOut:
    return ConditionOut(id=c.id, name=c.name, status=c.status, noted_on=c.noted_on, updated_at=as_utc(c.updated_at),
                        history=[ConditionEventOut(status=e.status, note=e.note, at=as_utc(e.at)) for e in c.events])


def prescription_out(db: Session, p: Prescription) -> PrescriptionOut:
    items = db.scalars(select(CareItem).where(CareItem.prescription_id == p.id).order_by(CareItem.created_at))
    author = db.get(User, p.recorded_by_id)
    return PrescriptionOut(
        id=p.id, doctor_name=p.doctor_name, facility_name=p.facility_name, prescribed_on=p.prescribed_on,
        diagnosis=p.diagnosis, notes=p.notes, photo_id=p.photo_id, referral_id=p.referral_id,
        recorded_by_role=author.role if author else None, created_at=as_utc(p.created_at),
        items=[care_out(i) for i in items],
    )


# ---------- Whole record ----------


def referral_brief(db: Session, r: Referral) -> ReferralBrief:
    facility = db.get(Facility, r.destination_facility_id)
    return ReferralBrief(id=r.id, code=r.code, status=r.status, triage=r.triage, facility_name=facility.name,
                         requested_service=r.requested_service, reason=r.reason, origin=r.origin,
                         created_at=as_utc(r.created_at))


def patient_record(db: Session, patient: Patient) -> PatientRecordOut:
    complete_finished_courses(db, patient.id)
    db.flush()
    today = local_today()
    items = list(db.scalars(select(CareItem).where(CareItem.patient_id == patient.id)
                            .order_by(CareItem.created_at.desc())))
    conditions = db.scalars(select(Condition).where(Condition.patient_id == patient.id)
                            .options(selectinload(Condition.events))
                            .order_by(Condition.updated_at.desc()))
    prescriptions = db.scalars(select(Prescription).where(Prescription.patient_id == patient.id)
                               .order_by(Prescription.created_at.desc()))
    encounters = db.scalars(select(Encounter).where(Encounter.patient_id == patient.id)
                            .options(selectinload(Encounter.medicines))
                            .order_by(Encounter.created_at.desc()).limit(50))
    referrals = db.scalars(select(Referral).where(Referral.patient_id == patient.id)
                           .order_by(Referral.created_at.desc()))
    asha = db.get(User, patient.created_by_id)
    return PatientRecordOut(
        patient=PatientOut.model_validate(patient),
        asha_name=asha.name if asha else None,
        conditions=[condition_out(c) for c in conditions],
        prescriptions=[prescription_out(db, p) for p in prescriptions],
        care_chart=[care_out(i, today) for i in items if i.status == CareStatus.ACTIVE],
        finished_care=[care_out(i, today) for i in items if i.status != CareStatus.ACTIVE][:FINISHED_CARE_SHOWN],
        vitals_history=[encounter_out(db, e) for e in encounters],
        referrals=[referral_brief(db, r) for r in referrals],
        vital_ranges=vital_ranges(),
    )


def register_rows(db: Session, asha: User, q: str | None = None) -> list[RegisterRowOut]:
    """The ASHA's register: every patient she looks after, with what needs attention."""
    stmt = select(Patient).where(Patient.created_by_id == asha.id).order_by(Patient.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((Patient.name.ilike(like)) | (Patient.phone.contains(q.strip()))
                          | (Patient.health_id.ilike(like)) | (Patient.address.ilike(like)))
    rows = []
    for p in db.scalars(stmt.limit(500)):
        last_visit = db.scalar(select(func.max(Encounter.created_at)).where(Encounter.patient_id == p.id))
        refs = list(db.scalars(select(Referral).where(Referral.patient_id == p.id)
                               .order_by(Referral.created_at.desc())))
        open_ref = next((r for r in refs if is_open(r.status)), None)
        meds = db.scalar(select(func.count(CareItem.id)).where(
            CareItem.patient_id == p.id, CareItem.status == CareStatus.ACTIVE, CareItem.kind == "MEDICINE"))
        rows.append(RegisterRowOut(
            patient=PatientOut.model_validate(p), last_visit_at=as_utc(last_visit),
            open_referral_code=open_ref.code if open_ref else None,
            open_referral_status=open_ref.status if open_ref else None,
            referrals_count=len(refs), active_medicines=meds or 0,
        ))
    return rows


# ---------- Death ----------


def record_death(db: Session, patient: Patient, actor: User, cause: str, died_at: datetime) -> list[Referral]:
    """Stop everything for a patient who died: open referrals, bed holds, ambulances, follow-ups, medicines."""
    from app.workflow import move, notify_facility_staff  # avoid an import loop

    patient.deceased_at, patient.death_cause = died_at, cause.strip()
    when = (as_utc(died_at) + LOCAL_UTC_OFFSET).strftime("%d %b %Y, %I:%M %p")
    stopped = []
    for referral in db.scalars(select(Referral).where(Referral.patient_id == patient.id)):
        if not is_open(referral.status):
            continue
        move(db, referral, Status.DECEASED, actor, note=f"Patient died on {when}. Cause: {cause.strip()}")
        for fu in db.scalars(select(FollowUp).where(FollowUp.referral_id == referral.id,
                                                    FollowUp.status != "COMPLETED")):
            fu.status = "MISSED"
        notify_facility_staff(db, referral.destination_facility_id, referral, "PATIENT_DIED",
                              f"{referral.code}: the patient {patient.name} died ({when}). The referral is stopped.")
        stopped.append(referral)
    for item in db.scalars(select(CareItem).where(CareItem.patient_id == patient.id,
                                                  CareItem.status == CareStatus.ACTIVE)):
        end_care(item, CareStatus.STOPPED, "Patient died")
    db.add(AuditLog(actor_id=actor.id, action="PATIENT_DECEASED", target_type="patient", target_id=patient.id))
    return stopped
