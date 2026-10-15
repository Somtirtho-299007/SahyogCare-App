from datetime import timedelta

import jwt
import pytest
from fastapi import Depends
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, OtpCode, User
from app.rules import Role
from app.security import ALGORITHM, require_roles
from app.timeutil import utcnow

ASHA = "asha@sahyogcare.test"
API = "/api/v1"


def request_code(client, email=ASHA):
    return client.post(f"{API}/auth/otp/request", json={"email": email})


def verify(client, code, email=ASHA):
    return client.post(f"{API}/auth/otp/verify", json={"email": email, "code": code})


def wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def test_full_login_flow(client, db):
    r = request_code(client, "  ASHA@SahyogCare.test ")  # spaces and capitals are ignored
    assert r.status_code == 202
    code = r.json()["dev_code"]
    assert len(code) == 6 and code.isdigit()

    stored = db.scalar(select(OtpCode))
    assert code not in stored.code_hash  # only a hash is stored

    r = verify(client, code)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "WORKER" and body["expires_in"] == 15 * 60

    me = client.get(f"{API}/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == ASHA

    assert db.scalar(select(AuditLog).where(AuditLog.action == "LOGIN")) is not None


def test_code_works_only_once(client):
    code = request_code(client).json()["dev_code"]
    assert verify(client, code).status_code == 200
    assert verify(client, code).json()["error"]["code"] == "OTP_INVALID"


def test_new_email_gets_a_code_and_a_pending_account(client, db):
    r = request_code(client, "stranger@example.com")
    assert r.status_code == 202 and r.json()["dev_code"]
    body = verify(client, r.json()["dev_code"], "stranger@example.com").json()
    assert body["user"]["approved"] is False
    h = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get(f"{API}/me", headers=h).json()["email"] == "stranger@example.com"
    # Waiting for approval: no records yet.
    assert client.get(f"{API}/referrals", headers=h).json()["error"]["code"] == "ACCOUNT_PENDING"


def test_inactive_user_cannot_get_a_code(client, db):
    user = db.scalar(select(User).where(User.email == ASHA))
    user.is_active = False
    db.commit()
    assert request_code(client).json()["dev_code"] is None


def test_wrong_codes_lock_after_five_attempts(client):
    code = request_code(client).json()["dev_code"]
    for left in (4, 3, 2, 1):
        r = verify(client, wrong(code))
        assert r.status_code == 400 and r.json()["error"]["details"]["attempts_left"] == left
    r = verify(client, wrong(code))
    assert r.status_code == 429 and r.json()["error"]["code"] == "OTP_LOCKED"
    # Even the right code no longer works.
    assert verify(client, code).json()["error"]["code"] == "OTP_LOCKED"


def test_expired_code(client, db):
    code = request_code(client).json()["dev_code"]
    otp = db.scalar(select(OtpCode))
    otp.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert verify(client, code).json()["error"]["code"] == "OTP_EXPIRED"


def test_resend_waits_sixty_seconds_and_old_code_dies(client, db):
    first = request_code(client).json()["dev_code"]
    r = request_code(client)
    assert r.status_code == 429 and r.json()["error"]["details"]["retry_after_seconds"] > 0

    otp = db.scalar(select(OtpCode))
    otp.created_at = utcnow() - timedelta(seconds=61)
    db.commit()
    second = request_code(client).json()["dev_code"]
    assert second
    if first != second:
        assert verify(client, first).status_code in (400, 429)
    assert verify(client, second).status_code == 200


def test_refresh_gives_new_tokens(client):
    tokens = verify(client, request_code(client).json()["dev_code"]).json()
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200 and r.json()["access_token"]


def test_tokens_cannot_be_swapped(client):
    tokens = verify(client, request_code(client).json()["dev_code"]).json()
    # A refresh token is not an access token...
    r = client.get(f"{API}/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401
    # ...and an access token is not a refresh token.
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401


def test_expired_and_forged_tokens_are_rejected(client, db):
    user = db.scalar(select(User).where(User.email == ASHA))
    now = utcnow()
    expired = jwt.encode(
        {"sub": user.id, "type": "access", "iat": now - timedelta(hours=1), "exp": now - timedelta(minutes=1)},
        settings.secret_key, algorithm=ALGORITHM,
    )
    r = client.get(f"{API}/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.json()["error"]["code"] == "TOKEN_EXPIRED"

    forged = jwt.encode(
        {"sub": user.id, "type": "access", "exp": now + timedelta(minutes=5)}, "not-the-secret", algorithm=ALGORITHM
    )
    r = client.get(f"{API}/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_deactivated_user_loses_access(client, db, auth):
    headers = auth("WORKER")
    user = db.scalar(select(User).where(User.role == "WORKER"))
    user.is_active = False
    db.commit()
    assert client.get(f"{API}/me", headers=headers).status_code == 401


@pytest.mark.parametrize("role,expected", [("DOCTOR", 200), ("FACILITY_STAFF", 200), ("WORKER", 403)])
def test_role_check(client, auth, role, expected):
    from app.main import app

    @app.get("/_test/medical-only")
    def _medical_only(user=Depends(require_roles(Role.DOCTOR, Role.FACILITY_STAFF))):
        return {"ok": True}

    try:
        r = client.get("/_test/medical-only", headers=auth(role))
        assert r.status_code == expected
        if expected == 403:
            assert r.json()["error"]["code"] == "FORBIDDEN"
    finally:
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/_test/medical-only"]


def test_bad_input_is_rejected(client):
    assert client.post(f"{API}/auth/otp/request", json={"email": "not-an-email"}).status_code == 422
    assert client.post(f"{API}/auth/otp/verify", json={"email": ASHA, "code": "12ab56"}).status_code == 422
