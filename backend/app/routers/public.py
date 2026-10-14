"""For patients: their own account. A patient signs in with the mobile number (or email)
their ASHA registered, proves it with a one-time code, and then sees everything that is
theirs: every referral (open and closed), history, medicines, readings, and the night
emergency button. There is no lookup by referral code any more: a code alone never opens
anything. See docs/WORKFLOW.md, "Patient accounts".

Where the code comes from:
- SMS to the registered mobile, when the SMS service is set up (SAHYOG_SMS_API_KEY);
- email, when the patient's record has an email;
- otherwise the ASHA shows a sign-in code on her phone (POST /patients/{id}/sign-in-code).

One mobile is often shared by a family: after the code, the patient picks who they are
from the people registered on that number.
"""

import logging
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app import ambulance
from app.config import settings
from app.db import get_db
from app.emailer import send_login_code
from app.errors import ApiError
from app.messaging import send_login_code_sms, sms_enabled
from app.models import AuditLog, Facility, FollowUp, OtpCode, Patient, Referral
from app.ratelimit import RateLimiter
from app.rules import (
    EMERGENCY_GUIDE,
    NATIONAL_AMBULANCE_NUMBER,
    OTP_MAX_ATTEMPTS,
    OTP_RESEND_AFTER,
    OTP_VALID_FOR,
    PATIENT_LOGINS_PER_MINUTE,
    is_open,
)
from app.schemas import (
    EmergencyIn,
    EmergencyOut,
    MyReferralOut,
    PatientChoiceOut,
    PatientChooseIn,
    PatientCodeRequestIn,
    PatientCodeRequestOut,
    PatientCodeVerifyIn,
    PatientRecordOut,
    PatientTokenOut,
    PublicAmbulance,
    PublicStep,
)
from app.security import ALGORITHM, current_patient, hash_otp, new_otp, otp_matches, patient_token_for
from app.timeutil import as_utc, utcnow
from app.workflow import commit, rerouted_to

router = APIRouter(prefix="/public", tags=["public"])
log = logging.getLogger("sahyogcare.public")
patient_login_limiter = RateLimiter(PATIENT_LOGINS_PER_MINUTE)


@router.get("/districts", response_model=list[str])
def districts() -> list[str]:
    """Areas this deployment serves (for the sign-up form)."""
    return settings.district_list


# ---------- The patient's own sign-in ----------

CHOOSE_MINUTES = 10


def patient_key(phone: str | None, email: str | None) -> str:
    """Login codes for patients live apart from staff codes (same table, own prefix)."""
    return f"pt:tel:{phone}" if phone else f"pt:email:{email}"


def _identity(body) -> tuple[str | None, str | None]:
    if bool(body.phone) == bool(body.email):
        raise ApiError(422, "VALIDATION_ERROR", "Enter your mobile number or your email.",
                       {"fields": {"phone": "Mobile number or email required"}})
    return body.phone, (body.email.strip().lower() if body.email else None)


def _patients_on(db: Session, phone: str | None, email: str | None) -> list[Patient]:
    """Everyone registered on this mobile number (a family may share one) or email."""
    cond = Patient.phone == phone if phone else Patient.email.ilike(email)
    return list(db.scalars(select(Patient).where(cond).order_by(Patient.created_at)))


def issue_patient_code(db: Session, key: str, valid_for: timedelta = OTP_VALID_FOR) -> str:
    """A fresh one-time code for this number/email; any older unused code stops working."""
    now = utcnow()
    db.execute(update(OtpCode).where(OtpCode.email == key, OtpCode.used_at.is_(None)).values(used_at=now))
    code = new_otp()
    db.add(OtpCode(email=key, code_hash=hash_otp(key, code), expires_at=now + valid_for))
    return code


@router.post("/login/request", response_model=PatientCodeRequestOut, status_code=202)
def patient_code_request(body: PatientCodeRequestIn, request: Request, db: Session = Depends(get_db)) -> PatientCodeRequestOut:
    """Step 1: send a code to the patient's registered mobile (SMS) or email.

    Without SMS, the answer says to ask the ASHA, who can show a code on her phone.
    The answer is the same whether or not anyone is registered on that number.
    """
    patient_login_limiter.check(request.client.host if request.client else "unknown")
    phone, email = _identity(body)
    # Without a working SMS service the patient asks their ASHA, who shows a code on her phone.
    channel = "email" if email else ("sms" if sms_enabled() or settings.is_development else "asha")
    if channel == "asha":
        return PatientCodeRequestOut(channel=channel)
    key = patient_key(phone, email)
    if not _patients_on(db, phone, email):
        return PatientCodeRequestOut(channel=channel)
    previous = db.scalar(select(OtpCode).where(OtpCode.email == key, OtpCode.used_at.is_(None))
                         .order_by(OtpCode.created_at.desc()).limit(1))
    if previous is not None and (wait := as_utc(previous.created_at) + OTP_RESEND_AFTER - utcnow()).total_seconds() > 0:
        seconds = int(wait.total_seconds()) + 1
        raise ApiError(429, "RATE_LIMITED", f"Please wait {seconds} seconds before asking for a new code.",
                       {"retry_after_seconds": seconds})
    code = issue_patient_code(db, key)
    try:
        if phone:
            send_login_code_sms(phone, code)
        else:
            send_login_code(email, code)
    except Exception as exc:
        db.rollback()
        if phone:
            # The SMS service is down or refused (e.g. no balance): fall back to the ASHA's code.
            log.exception("Patient login SMS could not be sent")
            return PatientCodeRequestOut(channel="asha")
        raise ApiError(503, "EMAIL_FAILED", "Could not send the code. Please try again.") from exc
    db.commit()
    return PatientCodeRequestOut(channel=channel, dev_code=code if settings.is_development else None)


def _choice_token(key: str, ids: list[str]) -> str:
    now = utcnow()
    payload = {"sub": key, "ids": ids, "type": "patient-choose", "iat": now, "exp": now + timedelta(minutes=CHOOSE_MINUTES)}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def _signed_in(db: Session, patient: Patient) -> PatientTokenOut:
    db.add(AuditLog(actor_id=None, action="PATIENT_LOGIN", target_type="patient", target_id=patient.id))
    db.commit()
    return PatientTokenOut(token=patient_token_for(patient), patient_id=patient.id, name=patient.name,
                           health_id=patient.health_id, language=patient.language)


@router.post("/login/verify", response_model=PatientChoiceOut)
def patient_code_verify(body: PatientCodeVerifyIn, request: Request, db: Session = Depends(get_db)) -> PatientChoiceOut:
    """Step 2: the code. One person on the number → signed in. Several → pick who you are."""
    patient_login_limiter.check(request.client.host if request.client else "unknown")
    phone, email = _identity(body)
    key = patient_key(phone, email)
    otp = db.scalar(select(OtpCode).where(OtpCode.email == key, OtpCode.used_at.is_(None))
                    .order_by(OtpCode.created_at.desc()).limit(1))
    if otp is None:
        raise ApiError(400, "OTP_INVALID", "This code is not valid. Please ask for a new code.")
    if utcnow() > as_utc(otp.expires_at):
        raise ApiError(400, "OTP_EXPIRED", "This code has expired. Please ask for a new code.")
    if otp.attempts >= OTP_MAX_ATTEMPTS:
        raise ApiError(429, "OTP_LOCKED", "Too many wrong attempts. Please ask for a new code.")
    if not otp_matches(key, body.code, otp.code_hash):
        otp.attempts += 1
        db.commit()
        if otp.attempts >= OTP_MAX_ATTEMPTS:
            raise ApiError(429, "OTP_LOCKED", "Too many wrong attempts. Please ask for a new code.")
        raise ApiError(400, "OTP_INVALID", "Wrong code.", {"attempts_left": OTP_MAX_ATTEMPTS - otp.attempts})
    otp.used_at = utcnow()
    people = _patients_on(db, phone, email)
    if not people:
        db.commit()
        raise ApiError(400, "OTP_INVALID", "This code is not valid. Please ask for a new code.")
    if len(people) == 1:
        return PatientChoiceOut(signed_in=_signed_in(db, people[0]))
    db.commit()
    return PatientChoiceOut(
        choose_token=_choice_token(key, [p.id for p in people]),
        people=[{"id": p.id, "name": p.name, "age": p.age, "sex": p.sex} for p in people],
    )


@router.post("/login/choose", response_model=PatientTokenOut)
def patient_choose(body: PatientChooseIn, db: Session = Depends(get_db)) -> PatientTokenOut:
    """Step 3 (shared phone only): which family member is signing in."""
    try:
        payload = jwt.decode(body.choose_token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise ApiError(401, "AUTH_REQUIRED", "That took too long. Please start again.") from exc
    if payload.get("type") != "patient-choose" or body.patient_id not in payload.get("ids", []):
        raise ApiError(401, "AUTH_REQUIRED", "Please start again.")
    patient = db.get(Patient, body.patient_id)
    if patient is None:
        raise ApiError(401, "AUTH_REQUIRED", "Please start again.")
    return _signed_in(db, patient)


@router.get("/me/referrals", response_model=list[MyReferralOut])
def my_referrals(patient: Patient = Depends(current_patient), db: Session = Depends(get_db)) -> list[MyReferralOut]:
    """Every referral of this patient, newest first: where it stands, the hospital, the ambulance."""
    refs = db.scalars(select(Referral).where(Referral.patient_id == patient.id).order_by(Referral.created_at.desc()))
    out = []
    for r in refs:
        facility = db.get(Facility, r.destination_facility_id)
        trip = ambulance.latest_trip(db, r)
        moved = rerouted_to(db, r)
        follow = db.scalar(select(FollowUp).where(FollowUp.referral_id == r.id).order_by(FollowUp.due_at.desc()).limit(1))
        out.append(MyReferralOut(
            id=r.id, code=r.code, status=r.status, is_open=is_open(r.status),
            facility_name=facility.name, facility_phone=facility.phone, requested_service=r.requested_service,
            reason=r.reason, triage=r.triage, created_at=as_utc(r.created_at),
            timeline=[PublicStep(status=e.to_status, at=as_utc(e.at)) for e in r.events],
            rerouted_to_facility=db.get(Facility, moved.destination_facility_id).name if moved else None,
            follow_up_due=as_utc(follow.due_at) if follow and follow.status != "COMPLETED" else None,
            ambulance=PublicAmbulance(status=trip.status, expected_at=ambulance.expected_at(trip),
                                      vehicle_number=trip.vehicle_number, driver_phone=trip.driver_phone)
            if trip else None,
        ))
    return out


@router.get("/me/record", response_model=PatientRecordOut)
def my_record(patient: Patient = Depends(current_patient), db: Session = Depends(get_db)) -> PatientRecordOut:
    """The patient's own history, prescriptions and medicine chart."""
    from app.records import patient_record

    out = patient_record(db, patient)
    db.commit()
    return out


@router.get("/emergency-conditions")
def emergency_conditions() -> list[dict]:
    """What the patient can choose on the emergency screen, with first-aid advice."""
    return [{"condition": c, "service": svc, "label": label, "precautions": tips}
            for c, (svc, label, tips) in EMERGENCY_GUIDE.items()]


@router.post("/emergency", response_model=EmergencyOut, status_code=201)
def emergency(body: EmergencyIn, patient: Patient = Depends(current_patient), db: Session = Depends(get_db)) -> EmergencyOut:
    """Night emergency: the system books the best hospital the ASHA would have chosen."""
    from app.emergency import book

    out = book(db, patient, body)
    commit(db)
    return out
