import json

import pytest
from sqlalchemy import func, select

from app import emailer
from app.accounts import ensure_coordinators
from app.config import settings
from app.models import OtpCode, User
from test_referrals import API, facility_id, post


def test_coordinator_adds_real_users(client, db, auth):
    coord = auth("COORDINATOR")
    r = post(client, "/users", coord, {"email": " Rina.ASHA@Gmail.com ", "name": "Rina", "role": "WORKER"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "rina.asha@gmail.com" and r.json()["district"] == "Nadia"
    assert post(client, "/users", coord, {"email": "rina.asha@gmail.com", "name": "R", "role": "WORKER"}
                ).json()["error"]["code"] == "DUPLICATE_USER"

    # Hospital staff and doctors must belong to a hospital in the district.
    assert post(client, "/users", coord, {"email": "desk@gmail.com", "name": "Desk", "role": "FACILITY_STAFF"}
                ).status_code == 422
    r = post(client, "/users", coord, {"email": "desk@gmail.com", "name": "Desk", "role": "FACILITY_STAFF",
                                        "facility_id": facility_id(db)})
    assert r.status_code == 201 and r.json()["facility_id"] == facility_id(db)

    emails = [u["email"] for u in client.get(f"{API}/users", headers=coord).json()]
    assert "rina.asha@gmail.com" in emails and "desk@gmail.com" in emails


def test_only_coordinators_manage_users(client, auth):
    body = {"email": "x@gmail.com", "name": "X", "role": "WORKER"}
    assert post(client, "/users", auth("WORKER"), body).status_code == 403
    assert client.get(f"{API}/users", headers=auth("FACILITY_STAFF")).status_code == 403


def test_switched_off_user_gets_no_code(client, db, auth):
    coord = auth("COORDINATOR")
    uid = post(client, "/users", coord, {"email": "leaver@gmail.com", "name": "L", "role": "WORKER"}).json()["id"]
    r = client.patch(f"{API}/users/{uid}", headers=coord, json={"is_active": False})
    assert r.json()["is_active"] is False
    assert post(client, "/auth/otp/request", {}, {"email": "leaver@gmail.com"}).status_code == 202
    assert db.scalar(select(func.count()).select_from(OtpCode).where(OtpCode.email == "leaver@gmail.com")) == 0

    me = client.get(f"{API}/me", headers=coord).json()["id"]
    assert client.patch(f"{API}/users/{me}", headers=coord, json={"is_active": False}).status_code == 422


def test_coordinators_from_settings(db, monkeypatch):
    monkeypatch.setattr(settings, "coordinator_emails", "Me@Gmail.com, other@gmail.com")
    assert ensure_coordinators(db) == 2
    assert ensure_coordinators(db) == 0  # safe on every restart
    me = db.scalar(select(User).where(User.email == "me@gmail.com"))
    assert me.role == "COORDINATOR" and me.district == "Nadia"


def test_brevo_sends_the_code(monkeypatch):
    sent = {}

    class Ok:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout):
        sent["url"], sent["key"] = request.full_url, request.headers["Api-key"]
        sent["body"] = json.loads(request.data)
        return Ok()

    monkeypatch.setattr(settings, "brevo_api_key", "test-key")
    monkeypatch.setattr(settings, "smtp_from", "SahyogCare <team@gmail.com>")
    monkeypatch.setattr(emailer.urllib.request, "urlopen", fake_urlopen)
    emailer.send_login_code("rina@gmail.com", "123456")
    assert sent["url"] == emailer.BREVO_URL and sent["key"] == "test-key"
    assert sent["body"]["sender"] == {"name": "SahyogCare", "email": "team@gmail.com"}
    assert sent["body"]["to"] == [{"email": "rina@gmail.com"}] and "123456" in sent["body"]["textContent"]


def test_production_without_email_settings_refuses(monkeypatch):
    for key, value in {"brevo_api_key": "", "smtp_host": "", "environment": "production",
                       "log_login_codes": False}.items():
        monkeypatch.setattr(settings, key, value)
    with pytest.raises(emailer.EmailNotConfigured):
        emailer.send_login_code("rina@gmail.com", "123456")
