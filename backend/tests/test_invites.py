"""Joining with a secret invite code from the district office."""

from datetime import timedelta

from sqlalchemy import select

from app.models import InviteCode
from app.timeutil import utcnow
from test_referrals import API, facility_id, make_referral, post
from test_signup import sign_up


def make_code(client, coord, **body):
    r = post(client, "/invite-codes", coord, body)
    assert r.status_code == 201, r.text
    return r.json()


def test_hospital_staff_join_instantly_with_a_code(client, db, auth):
    coord = auth("COORDINATOR")
    invite = make_code(client, coord, role="FACILITY_STAFF", facility_id=facility_id(db), label="Kalyani desk")
    assert invite["code"].startswith("HS-KAL-") and len(invite["code"]) == 15 and invite["usable"]

    me, user = sign_up(client, "desk.nurse@gmail.com")
    assert user["approved"] is False
    r = post(client, "/invite-codes/redeem", me, {"code": invite["code"].lower(), "name": "Rita Das"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "FACILITY_STAFF" and r.json()["approved"] and r.json()["facility_id"] == facility_id(db)

    # Straight into her hospital's queue, and the coordinator can see who used the code.
    ref = make_referral(client, db, auth("WORKER"))
    assert ref["id"] in [x["id"] for x in client.get(f"{API}/referrals", headers=me).json()]
    listed = client.get(f"{API}/invite-codes", headers=coord).json()[0]
    assert listed["uses"] == 1
    assert post(client, "/invite-codes/redeem", me, {"code": invite["code"], "name": "R"}).json()["error"]["code"] \
        == "ALREADY_APPROVED"


def test_asha_code_covers_the_district(client, db, auth):
    invite = make_code(client, auth("COORDINATOR"), role="WORKER", max_uses=2)
    assert invite["code"].startswith("AS-NAD-")
    for i in range(2):
        me, _ = sign_up(client, f"asha{i}@gmail.com")
        assert post(client, "/invite-codes/redeem", me, {"code": invite["code"], "name": f"ASHA {i}"}).status_code == 200
    me, _ = sign_up(client, "asha3@gmail.com")
    r = post(client, "/invite-codes/redeem", me, {"code": invite["code"], "name": "Too late"})
    assert r.json()["error"]["code"] == "INVITE_INVALID"


def test_coordinator_codes_are_single_use_and_short(client, db, auth):
    invite = make_code(client, auth("COORDINATOR"), role="COORDINATOR", max_uses=50, expires_in_days=300)
    assert invite["code"].startswith("DA-NAD-") and invite["max_uses"] == 1
    assert invite["expires_at"] < (utcnow() + timedelta(days=8)).isoformat()


def test_revoked_and_expired_codes_fail(client, db, auth):
    coord = auth("COORDINATOR")
    a = make_code(client, coord, role="WORKER")
    post(client, f"/invite-codes/{a['id']}/revoke", coord)
    b = make_code(client, coord, role="DOCTOR", facility_id=facility_id(db))
    db.get(InviteCode, b["id"]).expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    me, _ = sign_up(client, "x@gmail.com")
    for code in (a["code"], b["code"], "AS-NAD-NOTREAL1"):
        assert post(client, "/invite-codes/redeem", me, {"code": code, "name": "X"}).json()["error"]["code"] \
            == "INVITE_INVALID"


def test_guessing_is_limited(client, db, auth):
    me, _ = sign_up(client, "guesser@gmail.com")
    answers = [post(client, "/invite-codes/redeem", me, {"code": f"AS-NAD-GUESS00{i}", "name": "G"}).status_code
               for i in range(6)]
    assert answers[:5] == [400] * 5 and answers[5] == 429


def test_only_coordinators_make_codes(client, db, auth):
    assert post(client, "/invite-codes", auth("FACILITY_STAFF"), {"role": "WORKER"}).status_code == 403
    coord = auth("COORDINATOR")
    assert post(client, "/invite-codes", coord, {"role": "DOCTOR"}).status_code == 422  # needs a hospital
    assert post(client, "/invite-codes", coord, {"role": "WORKER", "facility_id": facility_id(db)}).status_code == 422
    assert db.scalar(select(InviteCode)) is None


# ---------- district office passphrase ----------


def test_office_enters_with_its_passphrase(client, db, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "office_passphrases", "Naihati:naihati_do_4821, Nadia:nadia_do_9930")
    me, user = sign_up(client, "do.naihati@gmail.com")
    wrong = post(client, "/invite-codes/office", me, {"district": "Naihati", "name": "DO", "passphrase": "nadia_do_9930"})
    assert wrong.json()["error"]["code"] == "PASSPHRASE_INVALID"
    r = post(client, "/invite-codes/office", me, {"district": "naihati", "name": "Naihati DO",
                                                  "passphrase": "naihati_do_4821"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "COORDINATOR" and r.json()["district"] == "Naihati" and r.json()["approved"]
    names = [f["name"] for f in client.get(f"{API}/facilities", headers=me).json()]
    assert names == ["Naihati State General Hospital"]


def test_office_passphrase_needs_configuring_and_limits_guessing(client, db, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "office_passphrases", "")
    me, _ = sign_up(client, "guess@gmail.com")
    body = {"district": "Nadia", "name": "X", "passphrase": "anything"}
    assert post(client, "/invite-codes/office", me, body).json()["error"]["code"] == "PASSPHRASE_INVALID"
    codes = [post(client, "/invite-codes/office", me, {**body, "passphrase": f"try{i}"}).status_code for i in range(5)]
    assert codes[-1] == 429
