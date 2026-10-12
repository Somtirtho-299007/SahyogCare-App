"""Login with a one-time code sent by email. See docs/WORKFLOW.md, "Login"."""

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.emailer import send_login_code
from app.errors import ApiError
from app.models import AuditLog, OtpCode, User
from app.rules import OTP_MAX_ATTEMPTS, OTP_RESEND_AFTER, OTP_VALID_FOR
from app.schemas import OtpRequestIn, OtpRequestOut, OtpVerifyIn, RefreshIn, TokensOut, UserOut
from app.security import (
    access_token_for,
    current_user,
    hash_otp,
    load_active_user,
    new_otp,
    otp_matches,
    read_token,
    refresh_token_for,
)
from app.timeutil import as_utc, utcnow

router = APIRouter(tags=["auth"])

GENERIC_SENT = "If this email is registered, a login code has been sent."


def _normalise(email: str) -> str:
    return email.strip().lower()


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
def request_code(body: OtpRequestIn, db: Session = Depends(get_db)) -> OtpRequestOut:
    email = _normalise(body.email)
    user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if user is None:
        # Same answer as for a registered email, so the API never reveals who has an account.
        return OtpRequestOut(message=GENERIC_SENT)

    now = utcnow()
    previous = _latest_unused_code(db, email)
    if previous is not None:
        wait = as_utc(previous.created_at) + OTP_RESEND_AFTER - now
        if wait.total_seconds() > 0:
            seconds = int(wait.total_seconds()) + 1
            raise ApiError(
                429, "RATE_LIMITED", f"Please wait {seconds} seconds before asking for a new code.",
                {"retry_after_seconds": seconds},
            )

    # Only the newest code is ever valid.
    db.execute(update(OtpCode).where(OtpCode.email == email, OtpCode.used_at.is_(None)).values(used_at=now))
    code = new_otp()
    db.add(OtpCode(email=email, code_hash=hash_otp(email, code), expires_at=now + OTP_VALID_FOR))

    try:
        send_login_code(email, code)
    except Exception as exc:
        db.rollback()
        raise ApiError(503, "EMAIL_FAILED", "Could not send the login code. Please try again.") from exc
    db.commit()

    return OtpRequestOut(message=GENERIC_SENT, dev_code=code if settings.is_development else None)


@router.post("/auth/otp/verify", response_model=TokensOut)
def verify_code(body: OtpVerifyIn, db: Session = Depends(get_db)) -> TokensOut:
    email = _normalise(body.email)
    otp = _latest_unused_code(db, email)
    if otp is None:
        raise ApiError(400, "OTP_INVALID", "This code is not valid. Please ask for a new code.")
    if utcnow() > as_utc(otp.expires_at):
        raise ApiError(400, "OTP_EXPIRED", "This code has expired. Please ask for a new code.")
    if otp.attempts >= OTP_MAX_ATTEMPTS:
        raise ApiError(429, "OTP_LOCKED", "Too many wrong attempts. Please ask for a new code.")

    if not otp_matches(email, body.code, otp.code_hash):
        otp.attempts += 1
        db.commit()
        left = OTP_MAX_ATTEMPTS - otp.attempts
        if left <= 0:
            raise ApiError(429, "OTP_LOCKED", "Too many wrong attempts. Please ask for a new code.")
        raise ApiError(400, "OTP_INVALID", "Wrong code.", {"attempts_left": left})

    otp.used_at = utcnow()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        db.commit()
        raise ApiError(401, "AUTH_REQUIRED", "This account is not active.")
    db.add(AuditLog(actor_id=user.id, action="LOGIN", target_type="user", target_id=user.id))
    db.commit()
    return _tokens(user)


@router.post("/auth/refresh", response_model=TokensOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokensOut:
    user = load_active_user(db, read_token(body.refresh_token, "refresh"))
    return _tokens(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)
