"""Personal codes: every approved person's own permanent password.

How it works
- First login: the person verifies their email (or phone) and asks to join. No code yet.
- The district office approves. A code unique to that one person is made, e.g. "K7QM-3XRA".
- The code is shown once, on their own dashboard, until they confirm they have written it down.
- Every later login: email/phone code first, then this personal code. Nobody can log in with
  another person's code, and nobody can log in to an approved account with the email alone.
- Forgotten? The district office taps "Reset code"; a new code is shown at the next login.

Only a keyed hash (HMAC with the server secret) is stored, never the code itself (except
the short time between issuing and the person confirming they noted it). The hash has a
unique index, so no two people can ever have the same code.
"""

import hashlib
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.timeutil import utcnow

# No 0/O or 1/I, so a code is easy to read and type.
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
LENGTH = 8  # 32^8 ≈ 1 trillion possible codes; wrong tries are limited too


def normalise(code: str) -> str:
    """Small letters, spaces and dashes don't matter when typing."""
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def keyed_hash(code: str) -> str:
    return hmac.new(settings.secret_key.encode(), b"staff-code:" + normalise(code).encode(), hashlib.sha256).hexdigest()


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def issue(db: Session, user: User) -> str:
    """Give the person a new personal code (replaces any old one). Shown once on their dashboard."""
    while True:
        code = _new_code()
        if db.scalar(select(User.id).where(User.code_hash == keyed_hash(code))) is None:
            break
    user.code_hash, user.pending_code, user.code_issued_at = keyed_hash(code), code, utcnow()
    return code


def matches(user: User, code: str) -> bool:
    return bool(user.code_hash) and hmac.compare_digest(user.code_hash, keyed_hash(code))


def needed_at_login(user: User) -> bool:
    """An approved person who has already seen their code must type it at every login."""
    return bool(user.approved and user.code_hash and not user.pending_code)


def clear(user: User) -> None:
    """Forget the code (district office reset): a new one is issued at the next login."""
    user.code_hash, user.pending_code, user.code_issued_at = None, None, None
