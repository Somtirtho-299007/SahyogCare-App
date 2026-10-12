"""One-time codes, tokens and the "who is calling" dependency."""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import timedelta

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.rules import OTP_LENGTH
from app.timeutil import utcnow

ALGORITHM = "HS256"


# ---------- One-time codes ----------


def new_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def hash_otp(email: str, code: str) -> str:
    # Keyed hash: a leaked database alone is not enough to check guesses offline.
    return hmac.new(settings.secret_key.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(email: str, code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(email, code), stored_hash)


# ---------- Tokens ----------


def _make_token(user: User, kind: str, lifetime: timedelta) -> str:
    now = utcnow()
    payload = {"sub": user.id, "role": user.role, "type": kind, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def access_token_for(user: User) -> str:
    return _make_token(user, "access", timedelta(minutes=settings.access_token_minutes))


def refresh_token_for(user: User) -> str:
    return _make_token(user, "refresh", timedelta(days=settings.refresh_token_days))


def read_token(token: str, expected_type: str) -> str:
    """Return the user id inside a valid token of the expected type."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "TOKEN_EXPIRED", "Your session has expired. Please log in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError(401, "AUTH_REQUIRED", "Invalid login token.") from exc
    if payload.get("type") != expected_type or not payload.get("sub"):
        raise ApiError(401, "AUTH_REQUIRED", "Invalid login token.")
    return payload["sub"]


# ---------- Dependencies ----------

_bearer = HTTPBearer(auto_error=False)


def load_active_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "AUTH_REQUIRED", "This account is not active.")
    return user


def current_user_any(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Any logged-in user, including people still waiting for approval."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise ApiError(401, "AUTH_REQUIRED", "Please log in.")
    return load_active_user(db, read_token(creds.credentials, "access"))


def current_user(user: User = Depends(current_user_any)) -> User:
    """A logged-in, approved user. Everything that touches records uses this."""
    if not user.approved:
        raise ApiError(403, "ACCOUNT_PENDING", "Your account is waiting for the coordinator's approval.")
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """Use as Depends(require_roles(Role.WORKER, ...))."""
    allowed = frozenset(roles)

    def _check(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise ApiError(403, "FORBIDDEN", "Your role cannot do this.")
        return user

    return _check
