"""Patients have their own account: mobile (or email) + one-time code, then everything of
theirs, and nothing of anyone else's. A referral code alone opens nothing."""

from sqlalchemy import select

from test_health_record import patient_headers
from test_referrals import API, KALYANI, facility_id, make_encounter, make_patient, make_referral, post

PHONE = "9876543210"


def ask(client, phone=PHONE):
    r = client.post(f"{API}/public/login/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    return r.json()


def test_one_person_on_the_number_signs_straight_in(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    sent = ask(client)
    assert sent["channel"] == "sms" and len(sent["dev_code"]) == 6
    r = client.post(f"{API}/public/login/verify", json={"phone": PHONE, "code": sent["dev_code"]}).json()
    assert r["signed_in"]["patient_id"] == ref["patient"]["id"] and r["people"] == []
    h = {"Authorization": f"Bearer {r['signed_in']['token']}"}
    record = client.get(f"{API}/public/me/record", headers=h).json()
    assert record["patient"]["id"] == ref["patient"]["id"] and record["referrals"][0]["code"] == ref["code"]
    # A staff login is not a patient login.
    assert client.get(f"{API}/public/me/record", headers=asha).status_code == 401


def test_a_family_sharing_one_phone_picks_who_they_are(client, db, auth):
    asha = auth("WORKER")
    mother = make_patient(client, asha, name="Mina Das")
    son = make_patient(client, asha, name="Bablu Das")
    other = make_patient(client, asha, name="Someone Else", phone="9123456780")
    sent = ask(client)
    r = client.post(f"{API}/public/login/verify", json={"phone": PHONE, "code": sent["dev_code"]}).json()
    assert r["signed_in"] is None and {p["name"] for p in r["people"]} == {"Mina Das", "Bablu Das"}
    # Only people on that number can be chosen.
    bad = client.post(f"{API}/public/login/choose", json={"choose_token": r["choose_token"], "patient_id": other["id"]})
    assert bad.status_code == 401
    ok = client.post(f"{API}/public/login/choose", json={"choose_token": r["choose_token"], "patient_id": son["id"]})
    assert ok.status_code == 200 and ok.json()["name"] == "Bablu Das"
    me = client.get(f"{API}/public/me/record", headers={"Authorization": f"Bearer {ok.json()['token']}"}).json()
    assert me["patient"]["id"] == son["id"] != mother["id"]


def test_wrong_codes_lock(client, db, auth):
    make_patient(client, auth("WORKER"))
    # Any number gets a code (new patients make their own account with it).
    assert ask(client, "9000000001")["dev_code"]
    sent = ask(client)
    for _ in range(4):
        r = client.post(f"{API}/public/login/verify", json={"phone": PHONE, "code": "000000"})
        assert r.json()["error"]["code"] in ("OTP_INVALID",)
    r = client.post(f"{API}/public/login/verify", json={"phone": PHONE, "code": "000000"})
    assert r.json()["error"]["code"] == "OTP_LOCKED"
    # Even the right code no longer works after the lock.
    r = client.post(f"{API}/public/login/verify", json={"phone": PHONE, "code": sent["dev_code"]})
    assert r.json()["error"]["code"] == "OTP_LOCKED"


def test_without_sms_the_asha_shows_a_code(client, db, auth, monkeypatch):
    from app.config import settings

    asha = auth("WORKER")
    p = make_patient(client, asha)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "log_login_codes", False)
    assert ask(client) == {"channel": "asha", "dev_code": None}
    shown = post(client, f"/patients/{p['id']}/sign-in-code", asha).json()
    assert shown["phone"] == PHONE and len(shown["code"]) == 6
    r = client.post(f"{API}/public/login/verify", json={"phone": PHONE, "code": shown["code"]}).json()
    assert r["signed_in"]["patient_id"] == p["id"]
    # The code works once only, and another ASHA cannot make codes for this patient.
    again = client.post(f"{API}/public/login/verify", json={"phone": PHONE, "code": shown["code"]})
    assert again.status_code == 400
    from test_referrals import new_user

    stranger = new_user(db, "other.asha@sahyogcare.test", "WORKER")
    assert post(client, f"/patients/{p['id']}/sign-in-code", stranger).status_code == 404


def test_email_on_the_record_also_works(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha, email="mina@example.com")
    r = client.post(f"{API}/public/login/request", json={"email": "Mina@Example.com"}).json()
    assert r["channel"] == "email" and r["dev_code"]
    v = client.post(f"{API}/public/login/verify", json={"email": "mina@example.com", "code": r["dev_code"]}).json()
    assert v["signed_in"]["patient_id"] == p["id"]


def test_my_referrals_lists_every_referral_open_and_closed(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    first = make_referral(client, db, asha)
    pid = first["patient"]["id"]
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor), ("outcome", doctor)):
        post(client, f"/referrals/{first['id']}/{path}", h)
    post(client, f"/referrals/{first['id']}/close", staff)
    # A new problem: a new referral under the same person (the closed one stays closed).
    e = make_encounter(client, asha, pid)
    second = post(client, "/referrals", asha, {"patient_id": pid, "encounter_id": e["id"],
                                                "destination_facility_id": facility_id(db, KALYANI),
                                                "requested_service": "General Medicine"}).json()
    mine = client.get(f"{API}/public/me/referrals", headers=patient_headers(client, pid)).json()
    assert [r["code"] for r in mine] == [second["code"], first["code"]]
    assert mine[0]["is_open"] and mine[0]["status"] == "CREATED" and mine[0]["facility_name"] == KALYANI
    assert not mine[1]["is_open"] and mine[1]["status"] == "CLOSED"
    assert [s["status"] for s in mine[1]["timeline"]][-1] == "CLOSED"
    assert post(client, f"/referrals/{first['id']}/accept", staff).status_code == 409


def test_one_patient_never_sees_another(client, db, auth):
    asha = auth("WORKER")
    mine = make_referral(client, db, asha, name="Mina Das")
    theirs = make_referral(client, db, asha, name="Other Person", phone="9123456780")
    h = patient_headers(client, mine["patient"]["id"])
    codes = [r["code"] for r in client.get(f"{API}/public/me/referrals", headers=h).json()]
    assert codes == [mine["code"]] and theirs["code"] not in codes


def test_lookup_by_referral_code_is_gone(client, db, auth):
    ref = make_referral(client, db, auth("WORKER"))
    r = client.post(f"{API}/public/referral-status", json={"code": ref["code"], "phone_last4": "3210"})
    assert r.status_code in (404, 405)
    r = client.post(f"{API}/public/patient-login", json={"code": ref["code"], "phone_last4": "3210"})
    assert r.status_code in (404, 405)


def test_patient_sign_in_is_rate_limited(client):
    from app.rules import PATIENT_LOGINS_PER_MINUTE

    for i in range(PATIENT_LOGINS_PER_MINUTE):
        client.post(f"{API}/public/login/request", json={"phone": f"90000{i:05d}"})
    r = client.post(f"{API}/public/login/request", json={"phone": "9000099999"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_sms_refused_by_the_service_falls_back_to_the_asha(client, db, auth, monkeypatch):
    """Fast2SMS answers 200 with return:false when it will not send (e.g. no balance)."""
    from app import messaging
    from app.config import settings

    make_patient(client, auth("WORKER"))
    monkeypatch.setattr(settings, "sms_api_key", "test-key")
    monkeypatch.setattr(messaging, "_post",
                        lambda *a, **k: b'{"return": false, "message": "Complete a transaction first"}')
    assert ask(client) == {"channel": "asha", "dev_code": None}
    assert client.get(f"{API}/health").json()["sms"] == "on"


# ---------- patients make their own account ----------


def verify(client, phone=PHONE):
    code = ask(client, phone)["dev_code"]
    r = client.post(f"{API}/public/login/verify", json={"phone": phone, "code": code})
    assert r.status_code == 200, r.text
    return r.json()


def signup(client, token, **extra):
    body = {"signup_token": token, "name": "Mina Das", "age": 30, "sex": "F", "address": "Kalyani B-block",
            "district": "Nadia", "consent": True, **extra}
    return client.post(f"{API}/public/login/signup", json=body)


def test_a_new_patient_makes_their_own_account(client, db, auth):
    from app.models import Notification

    office = auth("COORDINATOR")
    v = verify(client, "9000011111")
    assert v["new_account"] and v["signup_token"] and v["signed_in"] is None
    assert signup(client, v["signup_token"], consent=False).status_code == 422
    assert signup(client, v["signup_token"], district="Nowhere").status_code == 422
    r = signup(client, v["signup_token"])
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    me = client.get(f"{API}/public/me/record", headers=h).json()
    assert me["patient"]["name"] == "Mina Das" and me["patient"]["self_registered"] and me["patient"]["phone"] == "9000011111"
    assert client.get(f"{API}/public/me/referrals", headers=h).json() == []
    assert db.scalar(select(Notification.id).where(Notification.kind == "PATIENT_SELF_SIGNUP"))
    # The district office can see them; signing in again goes straight in.
    assert client.get(f"{API}/patients/{me['patient']['id']}", headers=office).status_code == 200
    assert verify(client, "9000011111")["signed_in"]["patient_id"] == me["patient"]["id"]


def test_someone_new_on_a_family_phone(client, db, auth):
    auth("COORDINATOR")
    mother = make_patient(client, auth("WORKER"), name="Mina Das")
    v = verify(client)
    assert v["signed_in"]["patient_id"] == mother["id"] and v["signup_token"]
    r = signup(client, v["signup_token"], name="Bablu Das", age=6, sex="M")
    assert r.status_code == 201
    v2 = client.post(f"{API}/public/login/verify", json={"phone": PHONE, "code": "000000"})  # old code used
    assert v2.status_code == 400
    # Same name again just signs that person in (no duplicate).
    again = signup(client, v["signup_token"], name="bablu  das", age=6)
    assert again.json()["patient_id"] == r.json()["patient_id"]


def test_asha_takes_a_self_registered_patient_onto_her_register(client, db, auth):
    auth("COORDINATOR")
    v = verify(client, "9000022222")
    own = signup(client, v["signup_token"], name="Rupa Sen").json()
    asha = auth("WORKER")
    p = client.post(f"{API}/patients", headers=asha, json={"name": "Rupa Sen", "age": 31, "sex": "F",
                                                           "phone": "9000022222", "consent_given": True}).json()
    assert p["id"] == own["patient_id"] and p["took_over_own_account"] and not p["self_registered"] and p["age"] == 31
    rows = client.get(f"{API}/patients/register", headers=asha).json()
    assert [r["patient"]["id"] for r in rows] == [own["patient_id"]]
    # A referral by the ASHA now shows in the patient's own account.
    ref_e = make_encounter(client, asha, p["id"])
    ref = post(client, "/referrals", asha, {"patient_id": p["id"], "encounter_id": ref_e["id"],
                                            "destination_facility_id": facility_id(db, KALYANI),
                                            "requested_service": "General Medicine"}).json()
    mine = client.get(f"{API}/public/me/referrals", headers={"Authorization": f"Bearer {own['token']}"}).json()
    assert [r["code"] for r in mine] == [ref["code"]]


def test_self_registered_patient_can_book_a_night_emergency(client, db, auth):
    auth("COORDINATOR")
    v = verify(client, "9000033333")
    t = signup(client, v["signup_token"]).json()["token"]
    out = client.post(f"{API}/public/emergency", headers={"Authorization": f"Bearer {t}"},
                      json={"condition": "LABOUR", "latitude": 23.17, "longitude": 88.56})
    assert out.status_code == 201, out.text
    assert out.json()["hospital_name"]
