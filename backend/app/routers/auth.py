"""Login with a one-time code sent by email, or by SMS to a mobile number when the
SMS service is set up (SAHYOG_SMS_API_KEY). See docs/WORKFLOW.md, "Login".

Anyone with a real email (or mobile number) can get a code. A first login creates the account,
which waits for the coordinator's approval of the role the person asks for
(see app/routers/access.py). Switched-off accounts get no code.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.emailer import send_login_code
from app.errors import ApiError
from app.messaging import send_login_code_sms, sms_enabled
from app.models import AuditLog, OtpCode, User
from app.ratelimit import RateLimiter
from app.rules import OTP_MAX_ATTEMPTS, OTP_REQUESTS_PER_MINUTE, OTP_RESEND_AFTER, OTP_VALID_FOR, Role
from app.schemas import OtpRequestIn, OtpRequestOut, OtpVerifyIn, RefreshIn, TokensOut, UserOut
from app.security import (
    access_token_for,
    current_user_any,
    hash_otp,
    load_active_user,
    new_otp,
    otp_matches,
    read_token,
    refresh_token_for,
)
from app.timeutil import as_utc, utcnow

router = APIRouter(tags=["auth"])

GENERIC_SENT = "A login code has been sent to this email."
GENERIC_SENT_SMS = "A login code has been sent by SMS to this number."
# Stops one machine from making the server send emails to thousands of addresses.
code_limiter = RateLimiter(OTP_REQUESTS_PER_MINUTE)


def _normalise(email: str) -> str:
    return email.strip().lower()


def phone_login_available() -> bool:
    return sms_enabled() or settings.is_development or settings.log_login_codes


def _identity(body) -> tuple[str, str | None, str | None]:
    """(key used for codes, email, phone). Exactly one of email / phone must be given."""
    if bool(body.email) == bool(body.phone):
        raise ApiError(422, "VALIDATION_ERROR", "Enter your email or your mobile number.",
                       {"fields": {"email": "Email or phone required"}})
    if body.phone:
        if not phone_login_available():
            raise ApiError(422, "PHONE_LOGIN_OFF", "Login by mobile number is not available yet. Please use your email.")
        return f"tel:{body.phone}", None, body.phone
    email = _normalise(body.email)
    return email, email, None


def _find_user(db: Session, email: str | None, phone: str | None) -> User | None:
    if phone:
        return db.scalar(select(User).where(User.phone == phone))
    return db.scalar(select(User).where(User.email == email))


def _latest_unused_code(db: Session, email: str) -> OtpCode | None:
    return db.scalar(
        select(OtpCode)
        .where(OtpCode.email == email, OtpCode.used_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )


def _tokens(user: User) -> TokensOut:
    return TokensOut(
        access_token=access_token_for(user),
        refresh_token=refresh_token_for(user),
        expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/auth/otp/request", response_model=OtpRequestOut, status_code=202)
def request_code(body: OtpRequestIn, request: Request, db: Session = Depends(get_db)) -> OtpRequestOut:
    code_limiter.check(request.client.host if request.client else "unknown")
    key, email, phone = _identity(body)
    sent_message = GENERIC_SENT_SMS if phone else GENERIC_SENT
    user = _find_user(db, email, phone)
    if user is not None and not user.is_active:
        # Switched off by the coordinator: same answer, but no code.
        return OtpRequestOut(message=sent_message)

    now = utcnow()
    previous = _latest_unused_code(db, key)
    if previous is not None:
        wait = as_utc(previous.created_at) + OTP_RESEND_AFTER - now
        if wait.total_seconds() > 0:
            seconds = int(wait.total_seconds()) + 1
            raise ApiError(
                429, "RATE_LIMITED", f"Please wait {seconds} seconds before asking for a new code.",
                {"retry_after_seconds": seconds},
            )

    # Only the newest code is ever valid.
    db.execute(update(OtpCode).where(OtpCode.email == key, OtpCode.used_at.is_(None)).values(used_at=now))
    code = new_otp()
    db.add(OtpCode(email=key, code_hash=hash_otp(key, code), expires_at=now + OTP_VALID_FOR))

    try:
        if phone:
            send_login_code_sms(phone, code)
        else:
            send_login_code(email, code)
    except Exception as exc:
        db.rollback()
        raise ApiError(503, "EMAIL_FAILED", "Could not send the login code. Please try again.") from exc
    db.commit()

    return OtpRequestOut(message=sent_message, dev_code=code if settings.is_development else None)


@router.post("/auth/otp/verify", response_model=TokensOut)
def verify_code(body: OtpVerifyIn, db: Session = Depends(get_db)) -> TokensOut:
    key, email, phone = _identity(body)
    otp = _latest_unused_code(db, key)
    if otp is None:
        raise ApiError(400, "OTP_INVALID", "This code is not valid. Please ask for a new code.")
    if utcnow() > as_utc(otp.expires_at):
        raise ApiError(400, "OTP_EXPIRED", "This code has expired. Please ask for a new code.")
    if otp.attempts >= OTP_MAX_ATTEMPTS:
        raise ApiError(429, "OTP_LOCKED", "Too many wrong attempts. Please ask for a new code.")

    if not otp_matches(key, body.code, otp.code_hash):
        otp.attempts += 1
        db.commit()
        left = OTP_MAX_ATTEMPTS - otp.attempts
        if left <= 0:
            raise ApiError(429, "OTP_LOCKED", "Too many wrong attempts. Please ask for a new code.")
        raise ApiError(400, "OTP_INVALID", "Wrong code.", {"attempts_left": left})

    otp.used_at = utcnow()
    user = _find_user(db, email, phone)
    if user is None:
        # First login: the email (or phone) is proven, so the account exists from now on. It
        # waits for approval (or is an approved ASHA straight away when auto-approval is on).
        name = email.split("@")[0] if email else f"User {phone[-4:]}"
        user = User(email=email, phone=phone, name=name, role=Role.WORKER,
                    district=settings.coordinator_district, approved=settings.auto_approve_asha)
        db.add(user)
        db.flush()
        db.add(AuditLog(actor_id=user.id, action="SIGNED_UP", target_type="user", target_id=user.id))
    elif not user.is_active:
        db.commit()
        raise ApiError(401, "AUTH_REQUIRED", "This account is not active.")
    db.add(AuditLog(actor_id=user.id, action="LOGIN", target_type="user", target_id=user.id))
    db.commit()
    return _tokens(user)


@router.post("/auth/refresh", response_model=TokensOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokensOut:
    user = load_active_user(db, read_token(body.refresh_token, "refresh"))
    return _tokens(user)


@router.get("/auth/methods")
def login_methods() -> dict[str, bool]:
    """Which login methods the sign-in screen should offer."""
    return {"email": True, "phone": phone_login_available()}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user_any)) -> UserOut:
    return UserOut.model_validate(user)
