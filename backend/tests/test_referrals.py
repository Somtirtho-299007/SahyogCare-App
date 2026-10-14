from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import Facility, FacilityService, FollowUp, Referral, User
from app.security import access_token_for
from app.timeutil import as_utc, utcnow

API = "/api/v1"
KALYANI = "Kalyani District Hospital"


# ---------- helpers ----------


def facility_id(db, name=KALYANI):
    return db.scalar(select(Facility.id).where(Facility.name == name))


def headers_for(user):
    return {"Authorization": f"Bearer {access_token_for(user)}"}


def new_user(db, email, role, facility=None, district="Nadia"):
    user = User(email=email, name=email, role=role, district=district,
                facility_id=facility_id(db, facility) if facility else None)
    db.add(user)
    db.commit()
    return headers_for(user)


def make_patient(client, h, name="Rina Das", phone="9876543210", **extra):
    body = {"name": name, "age": 28, "sex": "F", "phone": phone, "consent_given": True, **extra}
    r = client.post(f"{API}/patients", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def make_encounter(client, h, patient_id, triage="PRIORITY", vitals=None):
    body = {"reason": "Fever for 4 days", "triage": triage, "vitals": vitals or {"systolic": 118, "diastolic": 76}}
    r = client.post(f"{API}/patients/{patient_id}/encounters", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def make_referral(client, db, h, triage="PRIORITY", facility=KALYANI, service="General Medicine",
                  name="Rina Das", phone="9876543210", key=None):
    p = make_patient(client, h, name=name, phone=phone)
    e = make_encounter(client, h, p["id"], triage=triage)
    extra = {"Idempotency-Key": key} if key else {}
    r = client.post(f"{API}/referrals", headers={**h, **extra}, json={
        "patient_id": p["id"], "encounter_id": e["id"],
        "destination_facility_id": facility_id(db, facility), "requested_service": service,
    })
    assert r.status_code == 201, r.text
    return r.json()


def post(client, path, h, body=None):
    return client.post(f"{API}{path}", headers=h, json=body)


# ---------- the whole journey ----------


def test_full_referral_journey(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    ref = make_referral(client, db, asha)
    assert ref["status"] == "CREATED" and ref["code"].startswith("SC-")
    assert ref["vitals"]["systolic"] == 118 and ref["is_open"]
    rid = ref["id"]

    # The facility sees it in its queue.
    queue = client.get(f"{API}/referrals", headers=staff, params={"open": True}).json()
    assert [r["id"] for r in queue] == [rid]

    assert post(client, f"/referrals/{rid}/accept", staff).json()["status"] == "ACCEPTED"
    assert post(client, f"/referrals/{rid}/arrival", staff).json()["status"] == "ARRIVAL_RECORDED"
    assert post(client, f"/referrals/{rid}/consultation", doctor, {"note": "Seen"}).json()["status"] == "CONSULTED"

    r = post(client, f"/referrals/{rid}/outcome", doctor, {"note": "Treated", "follow_up_days": 3}).json()
    assert r["status"] == "FOLLOW_UP_DUE"  # handed back to the ASHA automatically
    assert r["events"][-1]["actor_role"] is None and r["events"][-1]["source"] == "SYSTEM"
    due = as_utc(db.scalar(select(FollowUp.due_at)))
    assert timedelta(days=2, hours=23) < due - utcnow() <= timedelta(days=3)

    # The ASHA cannot confirm the follow-up checkup; only the hospital can.
    assert post(client, f"/referrals/{rid}/close", asha).status_code == 403
    r = post(client, f"/referrals/{rid}/close", doctor, {"note": "Recovered"}).json()
    assert r["status"] == "CLOSED" and not r["is_open"]
    assert r["follow_up"]["status"] == "COMPLETED"
    assert [e["to_status"] for e in r["events"]] == [
        "CREATED", "ACCEPTED", "ARRIVAL_RECORDED", "CONSULTED", "OUTCOME_RECORDED", "FOLLOW_UP_DUE", "CLOSED",
    ]

    # The ASHA was told about every step someone else took.
    kinds = {n["kind"] for n in client.get(f"{API}/notifications", headers=asha).json()}
    assert {"STATUS_ACCEPTED", "STATUS_ARRIVAL_RECORDED", "STATUS_CONSULTED", "STATUS_FOLLOW_UP_DUE"} <= kinds
    assert "STATUS_CLOSED" in kinds  # the hospital closed it, so she is told

    # Accepting taught the system the service is available there.
    svc = db.scalar(select(FacilityService).where(FacilityService.service == "General Medicine",
                                                  FacilityService.facility_id == facility_id(db)))
    db.refresh(svc)
    assert svc.availability == "AVAILABLE"


# ---------- rules ----------


def test_roles_and_order_are_enforced(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    rid = make_referral(client, db, asha)["id"]

    r = post(client, f"/referrals/{rid}/accept", asha)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert post(client, f"/referrals/{rid}/accept", doctor).status_code == 403

    r = post(client, f"/referrals/{rid}/arrival", staff)  # not accepted yet
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert r.json()["error"]["details"]["current_status"] == "CREATED"

    post(client, f"/referrals/{rid}/accept", staff)
    post(client, f"/referrals/{rid}/arrival", staff)
    assert post(client, f"/referrals/{rid}/consultation", staff).status_code == 403
    assert post(client, f"/referrals/{rid}/close", doctor).status_code == 409  # can't skip to closed


def test_records_are_private_to_their_owners(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    other_asha = new_user(db, "asha2@sahyogcare.test", "WORKER")
    other_staff = new_user(db, "staff2@sahyogcare.test", "FACILITY_STAFF", facility="Haringhata Primary Health Centre")
    far_coordinator = new_user(db, "coord2@sahyogcare.test", "COORDINATOR", district="Elsewhere")

    for h in (other_asha, other_staff, far_coordinator):
        assert client.get(f"{API}/referrals/{ref['id']}", headers=h).status_code == 404
        assert client.get(f"{API}/patients/{ref['patient']['id']}", headers=h).status_code == 404
        assert client.get(f"{API}/referrals", headers=h).json() == []
        assert post(client, f"/referrals/{ref['id']}/accept", h).status_code == 404

    # The receiving facility and the district coordinator can see it.
    assert client.get(f"{API}/referrals/{ref['id']}", headers=auth("FACILITY_STAFF")).status_code == 200
    assert client.get(f"{API}/referrals/{ref['id']}", headers=auth("COORDINATOR")).status_code == 200
    assert client.get(f"{API}/patients/{ref['patient']['id']}", headers=auth("DOCTOR")).status_code == 200


def test_rejection_teaches_availability(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha, service="Diagnostics")

    r = post(client, f"/referrals/{ref['id']}/reject", staff, {"reason": "OTHER"})
    assert r.status_code == 422  # "Other" needs a note

    r = post(client, f"/referrals/{ref['id']}/reject", staff, {"reason": "SERVICE_UNAVAILABLE", "note": "Machine down"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "REJECTED" and body["rejection_reason"] == "SERVICE_UNAVAILABLE" and not body["is_open"]

    # The next ASHA searching for Diagnostics sees Kalyani last, marked unavailable.
    results = client.get(f"{API}/facilities", headers=asha, params={"service": "Diagnostics"}).json()
    assert results[-1]["name"] == KALYANI
    diag = next(s for s in results[-1]["services"] if s["service"] == "Diagnostics")
    assert diag["availability"] == "UNAVAILABLE" and diag["availability_note"] == "Requested service not available"

    msgs = [n["message"] for n in client.get(f"{API}/notifications", headers=asha).json()]
    assert any("could not take" in m for m in msgs)

    # After a rejection the ASHA can refer the same patient again.
    e = make_encounter(client, asha, ref["patient"]["id"])
    r = client.post(f"{API}/referrals", headers=asha, json={
        "patient_id": ref["patient"]["id"], "encounter_id": e["id"],
        "destination_facility_id": facility_id(db, "Nadia Sub-Divisional Hospital"), "requested_service": "Diagnostics",
    })
    assert r.status_code == 201


def test_rejection_reason_list(client, auth):
    reasons = client.get(f"{API}/referral-rejection-reasons", headers=auth("FACILITY_STAFF")).json()
    assert {r["code"] for r in reasons if r["marks_service_unavailable"]} == {"SERVICE_UNAVAILABLE", "NO_DOCTOR_AVAILABLE"}


def test_one_open_referral_per_patient_per_facility(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    e = make_encounter(client, asha, ref["patient"]["id"])
    r = client.post(f"{API}/referrals", headers=asha, json={
        "patient_id": ref["patient"]["id"], "encounter_id": e["id"],
        "destination_facility_id": facility_id(db), "requested_service": "Emergency",
    })
    assert r.status_code == 409 and r.json()["error"]["details"]["referral_id"] == ref["id"]


def test_retries_do_not_create_duplicates(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    e = make_encounter(client, asha, p["id"])
    body = {"patient_id": p["id"], "encounter_id": e["id"],
            "destination_facility_id": facility_id(db), "requested_service": "General Medicine"}
    h = {**asha, "Idempotency-Key": "phone-1-op-7"}
    first = client.post(f"{API}/referrals", headers=h, json=body).json()
    second = client.post(f"{API}/referrals", headers=h, json=body)
    assert second.json()["id"] == first["id"]
    assert db.scalar(select(func.count()).select_from(Referral)) == 1


def test_service_must_be_listed(client, db, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    e = make_encounter(client, asha, p["id"])
    r = client.post(f"{API}/referrals", headers=asha, json={
        "patient_id": p["id"], "encounter_id": e["id"],
        "destination_facility_id": facility_id(db, "Haringhata Primary Health Centre"), "requested_service": "Paediatrics",
    })
    assert r.status_code == 422 and r.json()["error"]["code"] == "SERVICE_NOT_LISTED"


def test_most_urgent_first(client, db, auth):
    asha = auth("WORKER")
    make_referral(client, db, asha, triage="ROUTINE", name="A", phone="9000000001")
    make_referral(client, db, asha, triage="EMERGENCY", name="B", phone="9000000002", service="Emergency")
    make_referral(client, db, asha, triage="PRIORITY", name="C", phone="9000000003")
    queue = client.get(f"{API}/referrals", headers=auth("FACILITY_STAFF")).json()
    assert [r["triage"] for r in queue] == ["EMERGENCY", "PRIORITY", "ROUTINE"]


# ---------- patients and encounters ----------


def test_patient_rules(client, auth):
    asha = auth("WORKER")
    base = {"name": "Mita", "age": 30, "phone": "9876500000", "consent_given": True}
    r = client.post(f"{API}/patients", headers=asha, json={**base, "consent_given": False})
    assert r.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert client.post(f"{API}/patients", headers=asha, json={**base, "phone": "12345"}).status_code == 422
    assert client.post(f"{API}/patients", headers=asha, json={**base, "age": 130}).status_code == 422
    assert client.post(f"{API}/patients", headers=auth("DOCTOR"), json=base).status_code == 403

    first = client.post(f"{API}/patients", headers=asha, json=base).json()
    assert first["possible_duplicate_of"] is None
    again = client.post(f"{API}/patients", headers=asha, json={**base, "name": " MITA ", "phone": "98765 00000"}).json()
    assert again["possible_duplicate_of"] == first["id"]  # warned, not blocked

    found = client.get(f"{API}/patients", headers=asha, params={"q": "mit"}).json()
    assert len(found) == 2


def test_vitals_are_checked_and_suggest_triage(client, auth):
    asha = auth("WORKER")
    p = make_patient(client, asha)
    r = client.post(f"{API}/patients/{p['id']}/encounters", headers=asha,
                    json={"reason": "x", "triage": "ROUTINE", "vitals": {"systolic": 1200}})
    assert r.status_code == 422 and "systolic" in r.json()["error"]["details"]["fields"]

    e = make_encounter(client, asha, p["id"], triage="ROUTINE", vitals={"spo2": 86})
    assert "Emergency" in e["triage_suggestion"] and e["triage"] == "ROUTINE"  # ASHA still decides
    e = make_encounter(client, asha, p["id"], triage="EMERGENCY", vitals={"spo2": 86})
    assert e["triage_suggestion"] is None  # already Emergency, nothing to suggest

    r = client.post(f"{API}/patients/{p['id']}/encounters", headers=asha, json={
        "reason": "Diabetes check", "triage": "ROUTINE", "vitals": {"glucose_mg_dl": 180},
        "medicines": [{"name": "Metformin", "dose": "500 mg", "frequency": "Twice a day"}],
    })
    assert r.json()["medicines"][0]["name"] == "Metformin"
    history = client.get(f"{API}/patients/{p['id']}/encounters", headers=asha).json()
    assert len(history) == 3


# ---------- referral pass ----------


def test_referral_pass_records_arrival(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    qr = client.get(f"{API}/referrals/{ref['id']}/pass", headers=asha).json()["qr_text"]
    assert qr.startswith("SC1.")

    r = post(client, "/referral-passes/verify", staff, {"qr_text": qr})
    assert r.status_code == 200
    body = r.json()
    assert body["already_recorded"] is False
    assert body["referral"]["status"] == "ARRIVAL_RECORDED"  # accepted on arrival, then arrived
    assert [e["to_status"] for e in body["referral"]["events"]] == ["CREATED", "ACCEPTED", "ARRIVAL_RECORDED"]

    again = post(client, "/referral-passes/verify", staff, {"qr_text": qr}).json()
    assert again["already_recorded"] is True and again["referral"]["status"] == "ARRIVAL_RECORDED"


def test_forged_and_wrong_facility_passes(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    qr = client.get(f"{API}/referrals/{ref['id']}/pass", headers=asha).json()["qr_text"]

    prefix, payload, sig = qr.split(".")
    tampered = ".".join([prefix, payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB"), sig])
    for bad in (tampered, "hello", "SC1.x.y"):
        r = post(client, "/referral-passes/verify", staff, {"qr_text": bad})
        assert r.status_code == 400 and r.json()["error"]["code"] == "PASS_INVALID"

    elsewhere = new_user(db, "staff3@sahyogcare.test", "FACILITY_STAFF", facility="Haringhata Primary Health Centre")
    r = post(client, "/referral-passes/verify", elsewhere, {"qr_text": qr})
    assert r.status_code == 403 and r.json()["error"]["code"] == "PASS_WRONG_FACILITY"
    assert post(client, "/referral-passes/verify", asha, {"qr_text": qr}).status_code == 403  # only facility staff scan


def test_offline_scan_keeps_scan_time(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    qr = client.get(f"{API}/referrals/{ref['id']}/pass", headers=asha).json()["qr_text"]
    post(client, f"/referrals/{ref['id']}/accept", staff)

    scanned = (utcnow() + timedelta(minutes=1)).isoformat()
    r = post(client, "/referral-passes/verify", staff, {"qr_text": qr, "scanned_at": scanned}).json()
    last = r["referral"]["events"][-1]
    assert last["to_status"] == "ARRIVAL_RECORDED" and last["source"] == "OFFLINE_PASS"


def test_offline_scan_of_rejected_referral_is_a_conflict(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    qr = client.get(f"{API}/referrals/{ref['id']}/pass", headers=asha).json()["qr_text"]
    post(client, f"/referrals/{ref['id']}/reject", staff, {"reason": "NO_BEDS"})
    r = post(client, "/referral-passes/verify", staff, {"qr_text": qr, "scanned_at": utcnow().isoformat()})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SYNC_CONFLICT"
    assert client.get(f"{API}/referrals/{ref['id']}/pass", headers=asha).status_code == 409


# ---------- public lookup ----------


def test_patient_can_check_status_with_code_and_phone(client, db, auth):
    ref = make_referral(client, db, auth("WORKER"))
    post(client, f"/referrals/{ref['id']}/accept", auth("FACILITY_STAFF"))

    r = client.post(f"{API}/public/referral-status", json={"code": ref["code"].lower(), "phone_last4": "3210"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ACCEPTED" and body["facility_name"] == KALYANI
    assert [s["status"] for s in body["timeline"]] == ["CREATED", "ACCEPTED"]
    assert "vitals" not in body and "patient" not in body and body["checklist"]

    wrong_phone = client.post(f"{API}/public/referral-status", json={"code": ref["code"], "phone_last4": "0000"})
    wrong_code = client.post(f"{API}/public/referral-status", json={"code": "SC-ZZZZZZ", "phone_last4": "3210"})
    assert wrong_phone.status_code == wrong_code.status_code == 404
    assert wrong_phone.json()["error"]["message"] == wrong_code.json()["error"]["message"]


def test_public_lookup_is_rate_limited(client):
    from app.rules import PUBLIC_LOOKUPS_PER_MINUTE

    for _ in range(PUBLIC_LOOKUPS_PER_MINUTE):
        client.post(f"{API}/public/referral-status", json={"code": "SC-ZZZZZZ", "phone_last4": "0000"})
    r = client.post(f"{API}/public/referral-status", json={"code": "SC-ZZZZZZ", "phone_last4": "0000"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


# ---------- notifications ----------


def test_notifications_are_private_and_can_be_marked_read(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    post(client, f"/referrals/{ref['id']}/accept", auth("FACILITY_STAFF"))

    unread = client.get(f"{API}/notifications", headers=asha, params={"unread": True}).json()
    assert len(unread) == 1 and ref["code"] in unread[0]["message"]
    nid = unread[0]["id"]

    assert post(client, f"/notifications/{nid}/read", auth("DOCTOR")).status_code == 404
    assert post(client, f"/notifications/{nid}/read", asha).json()["read_at"] is not None
    assert client.get(f"{API}/notifications", headers=asha, params={"unread": True}).json() == []
