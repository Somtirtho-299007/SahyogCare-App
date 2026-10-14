"""Anyone can sign up with their email; the coordinator approves the role they ask for."""

from sqlalchemy import select

from app.config import settings
from app.models import Notification, User
from test_referrals import API, facility_id, make_referral, post


def sign_up(client, email):
    code = client.post(f"{API}/auth/otp/request", json={"email": email}).json()["dev_code"]
    body = client.post(f"{API}/auth/otp/verify", json={"email": email, "code": code}).json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


def test_staff_sign_up_needs_approval(client, db, auth):
    me, user = sign_up(client, "Nurse.Rita@Gmail.com")
    assert user["approved"] is False and user["email"] == "nurse.rita@gmail.com"

    # Asking for a hospital role needs the hospital.
    assert post(client, "/access-requests", me, {"role": "FACILITY_STAFF", "name": "Rita"}).status_code == 422
    r = post(client, "/access-requests", me, {"role": "FACILITY_STAFF", "name": "Rita Das",
                                              "facility_id": facility_id(db), "note": "Kalyani desk, night shift"})
    assert r.status_code == 201 and r.json()["status"] == "PENDING"
    assert client.get(f"{API}/access-requests/mine", headers=me).json()["facility_name"] == "Kalyani District Hospital"

    # Still no access, and the coordinator is told.
    assert client.get(f"{API}/referrals", headers=me).status_code == 403
    coord_id = db.scalar(select(User.id).where(User.email == "coordinator@sahyogcare.test"))
    assert db.scalar(select(Notification).where(Notification.user_id == coord_id,
                                                Notification.kind == "ACCESS_REQUEST")) is not None

    coord = auth("COORDINATOR")
    pending = client.get(f"{API}/access-requests", headers=coord).json()
    assert [p["email"] for p in pending] == ["nurse.rita@gmail.com"]
    approved = post(client, f"/access-requests/{pending[0]['id']}/approve", coord)
    assert approved.json()["status"] == "APPROVED"
    assert post(client, f"/access-requests/{pending[0]['id']}/approve", coord).json()["error"]["code"] == "ALREADY_DECIDED"

    # Same login, now with access to her hospital's queue.
    after = client.get(f"{API}/me", headers=me).json()
    assert after["approved"] and after["role"] == "FACILITY_STAFF" and after["name"] == "Rita Das"
    asha_ref = make_referral(client, db, auth("WORKER"))
    assert asha_ref["id"] in [x["id"] for x in client.get(f"{API}/referrals", headers=me).json()]


def test_rejected_request_keeps_no_access(client, db, auth):
    me, _ = sign_up(client, "someone@gmail.com")
    rid = post(client, "/access-requests", me, {"role": "FACILITY_STAFF", "facility_id": facility_id(db), "name": "Someone"}).json()["id"]
    r = post(client, f"/access-requests/{rid}/reject", auth("COORDINATOR"), {"note": "Not from this hospital"})
    assert r.json()["status"] == "REJECTED"
    assert client.get(f"{API}/dashboard/summary", headers=me).status_code == 403


def test_asha_can_be_approved_automatically(client, db, monkeypatch):
    monkeypatch.setattr(settings, "auto_approve_asha", True)
    me, user = sign_up(client, "asha.mina@gmail.com")
    assert user["approved"] is True and user["role"] == "WORKER"
    r = post(client, "/access-requests", me, {"role": "WORKER", "name": "Mina Biswas"})
    assert r.json()["status"] == "APPROVED"
    # Hospital roles still wait for a person.
    me2, _ = sign_up(client, "doc@gmail.com")
    r = post(client, "/access-requests", me2, {"role": "DOCTOR", "name": "Dr Sen", "facility_id": facility_id(db)})
    assert r.json()["status"] == "PENDING"


def test_only_coordinators_decide(client, auth):
    assert client.get(f"{API}/access-requests", headers=auth("FACILITY_STAFF")).status_code == 403


def test_switched_off_account_cannot_sign_in_again(client, db):
    me, user = sign_up(client, "gone@gmail.com")
    db.get(User, user["id"]).is_active = False
    db.commit()
    r = client.post(f"{API}/auth/otp/request", json={"email": "gone@gmail.com"})
    assert r.status_code == 202 and r.json()["dev_code"] is None


def test_code_requests_are_rate_limited(client):
    from app.rules import OTP_REQUESTS_PER_MINUTE as limit

    codes = [client.post(f"{API}/auth/otp/request", json={"email": f"p{i}@gmail.com"}).status_code
             for i in range(limit + 1)]
    assert codes[:limit] == [202] * limit and codes[limit] == 429
