"""Patient register, health record, care chart, photos, death, patient sign-in and night emergency."""

import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import messaging
from app.models import AmbulanceTrip, BedHold, CareItem, Notification, Patient, Referral, User
from app.timeutil import utcnow
from app.watchdog import run_watchdog
from test_beds import headers_of
from test_referrals import API, KALYANI, facility_id, make_encounter, make_patient, make_referral, new_user, post

# Smallest valid JPEG header + padding: enough for the "is it a photo" check.
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 200).decode()
RANAGHAT = "Ranaghat Community Health Centre"
IST = timedelta(hours=5, minutes=30)


@pytest.fixture(autouse=True)
def clean_outbox():
    messaging.outbox.clear()
    yield
    messaging.outbox.clear()


def at_local(hour: int, minute: int, day: date | None = None) -> datetime:
    """A UTC moment that is hour:minute in India on `day` (default today in India)."""
    day = day or (utcnow() + IST).date()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc) - IST


def patient_headers(client, code: str, last4: str = "3210") -> dict[str, str]:
    r = client.post(f"{API}/public/patient-login", json={"code": code, "phone_last4": last4})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def run_through_outcome(client, db, asha, staff, doctor, rid):
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor), ("outcome", doctor)):
        assert post(client, f"/referrals/{rid}/{path}", h).status_code == 200


# ---------- register and one record per patient ----------


def test_one_patient_many_referrals_stay_on_one_record(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    p = make_patient(client, asha, address="Chakdaha, near the Shiv temple", language="bn")
    assert p["health_id"].startswith("HID-") and p["address"].startswith("Chakdaha")

    # First illness: referral, treated, follow-up done by the hospital.
    e1 = make_encounter(client, asha, p["id"])
    r1 = post(client, "/referrals", asha, {"patient_id": p["id"], "encounter_id": e1["id"],
                                           "destination_facility_id": facility_id(db), "requested_service": "General Medicine"}).json()
    run_through_outcome(client, db, asha, staff, doctor, r1["id"])
    post(client, f"/referrals/{r1['id']}/close", doctor)
    # Months later, a new illness: a new referral on the SAME patient, not a new record.
    e2 = make_encounter(client, asha, p["id"], triage="ROUTINE")
    r2 = post(client, "/referrals", asha, {"patient_id": p["id"], "encounter_id": e2["id"],
                                           "destination_facility_id": facility_id(db), "requested_service": "General Medicine"})
    assert r2.status_code == 201

    record = client.get(f"{API}/patients/{p['id']}/record", headers=asha).json()
    assert [x["code"] for x in record["referrals"]] == [r2.json()["code"], r1["code"]]
    rows = client.get(f"{API}/patients/register", headers=asha).json()
    assert len(rows) == 1 and rows[0]["referrals_count"] == 2 and rows[0]["open_referral_code"] == r2.json()["code"]
    # Search by village or Health ID works.
    assert len(client.get(f"{API}/patients/register", headers=asha, params={"q": "Chakdaha"}).json()) == 1
    assert len(client.get(f"{API}/patients/register", headers=asha, params={"q": p["health_id"]}).json()) == 1
    # Another ASHA's register does not show her.
    other = new_user(db, "asha2@sahyogcare.test", "WORKER")
    assert client.get(f"{API}/patients/register", headers=other).json() == []
    assert client.get(f"{API}/patients/{p['id']}/record", headers=other).status_code == 404


def test_home_visit_all_ok_needs_no_referral(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    r = post(client, f"/patients/{p['id']}/encounters", asha,
             {"reason": "Routine visit — all OK", "kind": "HOME_VISIT", "vitals": {"systolic": 112, "diastolic": 74}})
    assert r.status_code == 201 and r.json()["kind"] == "HOME_VISIT"
    row = client.get(f"{API}/patients/register", headers=asha).json()[0]
    assert row["last_visit_at"] is not None and row["referrals_count"] == 0


# ---------- vitals with normal ranges, updated after the checkup ----------


def test_vitals_have_normal_ranges_and_flags(client, db, auth):
    asha = auth("WORKER")
    ranges = {x["field"]: x for x in client.get(f"{API}/vital-ranges").json()}
    assert ranges["spo2"]["label"] == "95–100 %" and ranges["pulse"]["low"] == 60
    p = make_patient(client, asha)
    e = make_encounter(client, asha, p["id"], vitals={"systolic": 150, "diastolic": 95, "spo2": 88, "pulse": 80})
    assert e["flags"] == {"systolic": "HIGH", "diastolic": "HIGH", "spo2": "LOW", "pulse": "NORMAL"}
    assert e["triage_suggestion"]  # low oxygen: suggests Emergency


def test_hospital_updates_vitals_after_checkup_and_referral_shows_them(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    ref = make_referral(client, db, asha)
    pid = ref["patient"]["id"]
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor)):
        post(client, f"/referrals/{ref['id']}/{path}", h)

    # After treatment everything is back to normal; the doctor records the new readings.
    r = post(client, f"/patients/{pid}/encounters", doctor,
             {"reason": "After treatment", "kind": "VITALS_UPDATE", "referral_id": ref["id"],
              "vitals": {"systolic": 116, "diastolic": 76, "spo2": 98, "temperature_c": 36.8}})
    assert r.status_code == 201 and r.json()["recorded_by_role"] == "DOCTOR"
    updated = client.get(f"{API}/referrals/{ref['id']}", headers=asha).json()
    assert updated["latest_vitals"]["spo2"] == 98
    assert set(updated["vitals_flags"].values()) == {"NORMAL"}
    assert updated["vitals"]["systolic"] == 118  # the readings at referral time are kept

    # The hospital can only add readings, not record home visits.
    assert post(client, f"/patients/{pid}/encounters", doctor, {"reason": "x", "kind": "HOME_VISIT"}).status_code == 403
    # A hospital that never received this patient cannot see or update them.
    other_doc = headers_of(db, "doctor.nadia@sahyogcare.test")
    assert post(client, f"/patients/{pid}/encounters", other_doc,
                {"reason": "x", "kind": "VITALS_UPDATE"}).status_code == 404


# ---------- medical history and prescriptions ----------


def test_condition_history_reads_like_a_timeline(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    ref = make_referral(client, db, asha)
    pid = ref["patient"]["id"]
    c = post(client, f"/patients/{pid}/conditions", asha, {"name": "Fatty liver", "note": "Seen on ultrasound"}).json()
    assert c["status"] == "ACTIVE"
    # The doctor (patient referred to his hospital) marks it cured; the old status stays in the history.
    cured = client.patch(f"{API}/conditions/{c['id']}", headers=doctor, json={"status": "RESOLVED", "note": "Normal now"}).json()
    assert cured["status"] == "RESOLVED" and [h["status"] for h in cured["history"]] == ["ACTIVE", "RESOLVED"]
    other = new_user(db, "asha3@sahyogcare.test", "WORKER")
    assert client.patch(f"{API}/conditions/{c['id']}", headers=other, json={"status": "ACTIVE"}).status_code == 404
    # The hospital desk can read but not write the history.
    assert post(client, f"/patients/{pid}/conditions", staff, {"name": "x"}).status_code == 403


def test_prescription_goes_onto_the_care_chart(client, db, auth):
    asha, doctor = auth("WORKER"), auth("DOCTOR")
    ref = make_referral(client, db, asha)
    pid = ref["patient"]["id"]
    rx = post(client, f"/patients/{pid}/prescriptions", asha, {
        "doctor_name": "Dr. S. Roy", "facility_name": KALYANI, "diagnosis": "Anaemia", "referral_id": ref["id"],
        "items": [
            {"name": "Iron Folic Acid", "dose": "1 tablet", "quantity": "30 tablets", "timings": ["MORNING"],
             "food": "AFTER", "duration_days": 30},
            {"name": "Eat green leafy vegetables", "kind": "PRACTICE", "category": "PREGNANCY"},
        ]}).json()
    assert rx["diagnosis"] == "Anaemia" and len(rx["items"]) == 2
    assert rx["items"][0]["end_date"] is not None and rx["items"][0]["days_left"] == 30

    record = client.get(f"{API}/patients/{pid}/record", headers=doctor).json()  # the doctor sees it all
    assert {i["name"] for i in record["care_chart"]} == {"Iron Folic Acid", "Eat green leafy vegetables"}
    assert record["prescriptions"][0]["doctor_name"] == "Dr. S. Roy"
    # Only the ASHA enters prescriptions (the doctor writes on paper as usual).
    assert post(client, f"/patients/{pid}/prescriptions", doctor, {"items": []}).status_code == 403


def test_course_marked_done_or_finished_by_date_leaves_the_chart(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    done_now = post(client, f"/patients/{p['id']}/care-items", asha, {"name": "Paracetamol", "timings": ["NIGHT"]}).json()
    old = post(client, f"/patients/{p['id']}/care-items", asha, {
        "name": "Amoxicillin", "dose": "500 mg", "timings": ["MORNING", "NIGHT"], "duration_days": 5,
        "start_date": (date.today() - timedelta(days=10)).isoformat()}).json()
    assert old["status"] == "ACTIVE"

    r = post(client, f"/care-items/{done_now['id']}/end", asha, {"status": "COMPLETED"})
    assert r.json()["status"] == "COMPLETED"
    assert post(client, f"/care-items/{done_now['id']}/end", asha, {}).status_code == 409

    record = client.get(f"{API}/patients/{p['id']}/record", headers=asha).json()
    assert record["care_chart"] == []  # the 5-day course that ended last week completed by itself
    finished = {i["name"]: i for i in record["finished_care"]}
    assert finished["Amoxicillin"]["end_reason"] == "Course finished" and finished["Paracetamol"]["status"] == "COMPLETED"


# ---------- photos ----------


def test_patient_photo_is_private_to_people_who_see_the_patient(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    r = post(client, "/photos", asha, {"data_url": JPEG, "owner_type": "patient", "owner_id": p["id"]})
    assert r.status_code == 201
    photo_id = r.json()["id"]
    assert client.get(f"{API}/patients/{p['id']}", headers=asha).json()["photo_id"] == photo_id
    got = client.get(f"{API}/photos/{photo_id}", headers=asha)
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    # Another ASHA and an unrelated hospital cannot open it; the patient can.
    assert client.get(f"{API}/photos/{photo_id}", headers=new_user(db, "a4@sahyogcare.test", "WORKER")).status_code == 404
    assert client.get(f"{API}/photos/{photo_id}", headers=auth("FACILITY_STAFF")).status_code == 404
    assert client.get(f"{API}/photos/{photo_id}", headers=patient_headers(client, p["health_id"])).status_code == 200
    # Not a photo, or not the ASHA's patient: refused.
    fake = "data:image/jpeg;base64," + base64.b64encode(b"hello world, not an image" * 3).decode()
    assert post(client, "/photos", asha, {"data_url": fake, "owner_type": "patient", "owner_id": p["id"]}).status_code == 422
    assert post(client, "/photos", auth("FACILITY_STAFF"), {"data_url": JPEG, "owner_type": "patient",
                                                           "owner_id": p["id"]}).status_code == 403


def test_asha_photo_at_sign_up_reaches_the_district_office(client, db, auth):
    from test_signup import sign_up

    me, user = sign_up(client, "new.asha@gmail.com")
    photo = post(client, "/photos", me, {"data_url": JPEG, "owner_type": "user"}).json()["id"]
    assert client.get(f"{API}/photos/{photo}", headers=me).status_code == 200  # her own, while waiting
    post(client, "/access-requests", me, {"role": "WORKER", "name": "Mina Pal", "district": "Nadia"})
    coord = auth("COORDINATOR")
    pending = client.get(f"{API}/access-requests", headers=coord).json()
    assert pending[0]["photo_id"] == photo
    assert client.get(f"{API}/photos/{photo}", headers=coord).status_code == 200


# ---------- death ----------


def test_patient_died_stops_everything(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha, triage="EMERGENCY")
    pid = ref["patient"]["id"]
    post(client, f"/referrals/{ref['id']}/ambulance", asha, {"pickup_note": "Village Chakdaha, blue house"})
    post(client, f"/patients/{pid}/care-items", asha, {"name": "ORS", "timings": ["MORNING"]})
    assert db.scalar(select(BedHold.status)) == "HELD"

    died_at = (utcnow() - timedelta(hours=1)).isoformat()
    future = (utcnow() + timedelta(hours=2)).isoformat()
    assert post(client, f"/patients/{pid}/deceased", asha, {"cause": "Cardiac arrest", "died_at": future}).status_code == 422
    r = post(client, f"/patients/{pid}/deceased", staff, {"cause": "Cardiac arrest", "died_at": died_at})
    assert r.status_code == 200 and r.json()["death_cause"] == "Cardiac arrest"

    stopped = client.get(f"{API}/referrals/{ref['id']}", headers=asha).json()
    assert stopped["status"] == "DECEASED" and not stopped["is_open"]
    assert "Cardiac arrest" in stopped["events"][-1]["note"]
    assert stopped["bed"]["status"] == "RELEASED" and stopped["ambulance"]["status"] == "CANCELLED"
    assert db.scalar(select(CareItem.status)) == "STOPPED"
    kinds = set(db.scalars(select(Notification.kind)))
    assert "STATUS_DECEASED" in kinds
    # Nothing new can be started for this patient, and it cannot be recorded twice.
    e = post(client, f"/patients/{pid}/encounters", asha, {"reason": "x", "kind": "HOME_VISIT"})
    assert e.json()["error"]["code"] == "PATIENT_DECEASED"
    assert post(client, f"/patients/{pid}/deceased", asha, {"cause": "x x", "died_at": died_at}).status_code == 409


# ---------- the patient's own sign-in ----------


def test_patient_signs_in_with_health_id_or_referral_code(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    pid = ref["patient"]["id"]
    hid = client.get(f"{API}/patients/{pid}", headers=asha).json()["health_id"]
    assert client.post(f"{API}/public/patient-login", json={"code": hid, "phone_last4": "0000"}).status_code == 404
    h = patient_headers(client, hid)
    record = client.get(f"{API}/public/me/record", headers=h).json()
    assert record["patient"]["id"] == pid and record["referrals"][0]["code"] == ref["code"]
    # A referral code works too; a staff login is not a patient login, and vice versa.
    patient_headers(client, ref["code"])
    assert client.get(f"{API}/public/me/record", headers=asha).status_code == 401
    assert client.get(f"{API}/referrals", headers=h).status_code == 401


# ---------- night emergency booked by the patient ----------


def test_night_emergency_books_the_best_hospital_and_tells_the_asha(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha, address="Haringhata, near the school")
    h = patient_headers(client, p["health_id"])
    conditions = {c["condition"]: c for c in client.get(f"{API}/public/emergency-conditions").json()}
    assert conditions["LABOUR"]["service"] == "Maternity"

    r = client.post(f"{API}/public/emergency", headers=h, json={"condition": "LABOUR", "note": "Water broke at 2 am",
                                                                "latitude": 23.17, "longitude": 88.56})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["service"] == "Maternity" and out["call"] == "108" and out["precautions"]
    assert out["hospital_name"] == RANAGHAT and out["bed_held"] and out["ambulance_requested"]

    referral = db.scalar(select(Referral).where(Referral.code == out["referral_code"]))
    assert referral.origin == "PATIENT_EMERGENCY" and referral.triage == "EMERGENCY"
    assert referral.events[0].actor_id is None and "ASHA could not be reached" in referral.events[0].note
    asha_id = db.scalar(select(User.id).where(User.email == "asha@sahyogcare.test"))
    assert db.scalar(select(Notification.id).where(Notification.user_id == asha_id,
                                                   Notification.kind == "PATIENT_EMERGENCY"))
    assert db.scalar(select(AmbulanceTrip.pickup_note)).startswith("Haringhata")
    # The ASHA gets it by email too (to read when she wakes); the family gets a confirmation.
    assert any(m["email"] == "asha@sahyogcare.test" for m in messaging.outbox)
    assert any(m["phone"] == p["phone"] and "108" in m["text"] for m in messaging.outbox)

    # Pressing again does not book a second hospital.
    again = client.post(f"{API}/public/emergency", headers=h, json={"condition": "LABOUR"}).json()
    assert again["already_open"] and again["referral_code"] == out["referral_code"]


def test_rejected_patient_emergency_is_rerouted_automatically(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    out = client.post(f"{API}/public/emergency", headers=patient_headers(client, p["health_id"]),
                      json={"condition": "LABOUR", "latitude": 23.17, "longitude": 88.56}).json()
    first = db.scalar(select(Referral).where(Referral.code == out["referral_code"]))
    staff = headers_of(db, "staff.ranaghat@sahyogcare.test")
    r = post(client, f"/referrals/{first.id}/reject", staff, {"reason": "NO_DOCTOR_AVAILABLE"})
    assert r.status_code == 200 and r.json()["rerouted_to_code"]
    new = db.scalar(select(Referral).where(Referral.rerouted_from_id == first.id))
    assert new.origin == "PATIENT_EMERGENCY" and "Re-routed automatically" in new.events[0].note
    assert new.destination_facility_id != first.destination_facility_id


def test_dead_patient_cannot_book_an_emergency(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    h = patient_headers(client, p["health_id"])
    post(client, f"/patients/{p['id']}/deceased", asha, {"cause": "Old age", "died_at": utcnow().isoformat()})
    assert client.post(f"{API}/public/emergency", headers=h, json={"condition": "OTHER"}).status_code == 409


# ---------- reminders ----------


def test_dose_reminder_goes_once_at_dose_time_in_the_patients_language(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha, language="bn")
    post(client, f"/patients/{p['id']}/care-items", asha,
         {"name": "Iron", "dose": "1 tablet", "timings": ["MORNING"], "food": "AFTER", "duration_days": 30})
    assert run_watchdog(db, now=at_local(7, 0))["dose_reminders"] == 0  # too early
    result = run_watchdog(db, now=at_local(8, 10))
    db.commit()
    assert result["dose_reminders"] == 1
    msg = messaging.outbox[-1]
    assert msg["phone"] == p["phone"] and "সকাল" in msg["text"] and "Iron" in msg["text"] and "খাবারের পরে" in msg["text"]
    assert run_watchdog(db, now=at_local(8, 20))["dose_reminders"] == 0  # never twice


def test_before_food_dose_is_reminded_earlier_and_reminders_can_be_turned_off(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    post(client, f"/patients/{p['id']}/care-items", asha, {"name": "Pantoprazole", "timings": ["MORNING"], "food": "BEFORE"})
    assert run_watchdog(db, now=at_local(7, 35))["dose_reminders"] == 1
    db.commit()
    q = make_patient(client, asha, name="Babu", phone="9123456780")
    client.patch(f"{API}/patients/{q['id']}", headers=asha, json={"reminders": False})
    post(client, f"/patients/{q['id']}/care-items", asha, {"name": "Iron", "timings": ["NIGHT"]})
    assert run_watchdog(db, now=at_local(21, 5))["dose_reminders"] == 0


def test_staff_reminded_to_update_old_bed_counts_at_shift_change(client, db, auth):
    from app.models import BedWard

    for w in db.scalars(select(BedWard)):
        w.updated_at = utcnow() - timedelta(hours=10)
    db.commit()
    assert run_watchdog(db, now=at_local(14, 0))["bed_update_reminders"] == 0
    result = run_watchdog(db, now=at_local(8, 5))
    db.commit()
    assert result["bed_update_reminders"] >= 1
    staff_id = db.scalar(select(User.id).where(User.email == "staff@sahyogcare.test"))
    assert db.scalar(select(Notification.message).where(Notification.user_id == staff_id,
                                                        Notification.kind.like("BED_UPDATE_%")))
    assert run_watchdog(db, now=at_local(8, 15))["bed_update_reminders"] == 0


# ---------- family messages, phone login, running the watchdog from outside ----------


def test_family_gets_sms_when_accepted_and_ambulance_sent(client, db, auth, monkeypatch):
    from app.config import settings

    sent = []
    monkeypatch.setattr(settings, "sms_api_key", "test-key")
    monkeypatch.setattr(messaging, "_send_sms", lambda phone, text: sent.append((phone, text)))
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    post(client, f"/referrals/{ref['id']}/ambulance", asha, {"pickup_note": "Blue house, Chakdaha"})
    post(client, f"/referrals/{ref['id']}/ambulance/dispatch", staff,
         {"eta_minutes": 20, "vehicle_number": "WB-52-1234", "driver_phone": "9800011122"})
    phones = {p for p, _ in sent}
    assert phones == {"9876543210"}
    assert any("WB-52-1234" in t and "9800011122" in t for _, t in sent)  # Bengali text, vehicle and driver
    assert any(KALYANI in t for _, t in sent)


def test_phone_login(client, db):
    r = client.post(f"{API}/auth/otp/request", json={"phone": "9812345678"})
    assert r.status_code == 202 and "SMS" in r.json()["message"]
    code = r.json()["dev_code"]
    tokens = client.post(f"{API}/auth/otp/verify", json={"phone": "9812345678", "code": code}).json()
    assert tokens["user"]["phone"] == "9812345678" and tokens["user"]["email"] is None
    assert client.post(f"{API}/auth/otp/request", json={}).status_code == 422
    assert client.post(f"{API}/auth/otp/request",
                       json={"phone": "9812345678", "email": "a@gmail.com"}).status_code == 422
    assert client.get(f"{API}/auth/methods").json() == {"email": True, "phone": True}


def test_watchdog_tick_needs_the_cron_secret(client, db, monkeypatch):
    from app.config import settings

    assert client.post(f"{API}/watchdog/tick").status_code == 404  # off when no secret is set
    monkeypatch.setattr(settings, "cron_secret", "s3cret-value")
    assert client.post(f"{API}/watchdog/tick", headers={"X-Cron-Secret": "wrong"}).status_code == 404
    r = client.post(f"{API}/watchdog/tick", headers={"X-Cron-Secret": "s3cret-value"})
    assert r.status_code == 200 and "dose_reminders" in r.json()


def test_rate_limiter_falls_back_to_memory_without_redis(monkeypatch):
    from app.config import settings
    from app.errors import ApiError
    from app.ratelimit import RateLimiter

    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1")  # nothing listens there
    limiter = RateLimiter(2)
    limiter.check("x")
    limiter.check("x")
    with pytest.raises(ApiError):
        limiter.check("x")


def test_emergency_when_already_referred_alerts_that_hospital_instead_of_booking_another(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    hid = client.get(f"{API}/patients/{ref['patient']['id']}", headers=asha).json()["health_id"]
    out = client.post(f"{API}/public/emergency", headers=patient_headers(client, hid), json={"condition": "CHEST_PAIN"}).json()
    assert out["already_open"] and out["referral_code"] == ref["code"]
    assert db.scalar(select(Notification.id).where(Notification.kind == "PATIENT_EMERGENCY"))
    assert db.scalar(select(Referral.id).where(Referral.origin == "PATIENT_EMERGENCY")) is None
