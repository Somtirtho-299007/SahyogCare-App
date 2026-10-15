"""Bed reservation, hospital recommendation and re-routing.

Seeded beds (see app/seed.py):
  Kalyani     GENERAL 10 total / 6 occupied (4 free), EMERGENCY 4 / 2 (2 free)
  Ranaghat    GENERAL 6 / 3 (3 free), MATERNITY 4 / 1
  Nadia SDH   GENERAL 12 / 8 (4 free), PAEDIATRIC 6 / 2
  Haringhata  GENERAL 3 / 1 (2 free), MATERNITY 2 / 0
"""

from datetime import timedelta

from sqlalchemy import select

from app.models import BedHold, BedWard, Notification, User
from app.security import access_token_for
from app.timeutil import utcnow
from app.watchdog import run_watchdog
from test_referrals import API, KALYANI, facility_id, make_encounter, make_patient, make_referral, post

RANAGHAT = "Ranaghat Community Health Centre"
NADIA = "Nadia Sub-Divisional Hospital"
HARINGHATA = "Haringhata Primary Health Centre"


def ward(client, h, db, name=KALYANI, ward_name="GENERAL"):
    f = client.get(f"{API}/facilities/{facility_id(db, name)}", headers=h).json()
    return next(w for w in f["wards"] if w["ward"] == ward_name)


def set_beds(client, db, h, name, ward_name, total, occupied):
    r = client.put(f"{API}/facilities/{facility_id(db, name)}/beds/{ward_name}", headers=h,
                   json={"total": total, "occupied": occupied})
    assert r.status_code == 200, r.text
    return r


def headers_of(db, email):
    return {"Authorization": f"Bearer {access_token_for(db.scalar(select(User).where(User.email == email)))}"}


def try_referral(client, db, h, facility=KALYANI, service="General Medicine", phone="9876500000", **extra):
    p = make_patient(client, h, name=f"Patient {phone}", phone=phone)
    e = make_encounter(client, h, p["id"], triage=extra.pop("triage", "PRIORITY"))
    return client.post(f"{API}/referrals", headers=h, json={
        "patient_id": p["id"], "encounter_id": e["id"], "destination_facility_id": facility_id(db, facility),
        "requested_service": service, **extra,
    })


# ---------- holding beds ----------


def test_referral_holds_a_bed(client, db, auth):
    asha = auth("WORKER")
    before = ward(client, asha, db)
    assert (before["free"], before["held"]) == (4, 0)

    ref = make_referral(client, db, asha)
    assert ref["bed"]["status"] == "HELD" and ref["bed"]["ward"] == "GENERAL"
    after = ward(client, asha, db)
    assert (after["free"], after["held"], after["occupied"]) == (3, 1, 6)


def test_service_without_a_ward_holds_nothing(client, db, auth):
    ref = make_referral(client, db, auth("WORKER"), service="Diagnostics")
    assert ref["bed"] is None


def test_full_ward_offers_alternatives(client, db, auth):
    asha, coord = auth("WORKER"), auth("COORDINATOR")
    set_beds(client, db, coord, KALYANI, "GENERAL", 10, 10)

    r = try_referral(client, db, asha)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "NO_BEDS_AVAILABLE" and err["details"]["ward"] == "GENERAL"
    names = [a["facility_name"] for a in err["details"]["alternatives"]]
    assert KALYANI not in names and len(names) == 3
    assert all(a["beds_free"] > 0 for a in err["details"]["alternatives"])

    # The ASHA may still send the patient when there is no other option; no bed is held.
    r = try_referral(client, db, asha, phone="9876500001", allow_without_bed=True)
    assert r.status_code == 201 and r.json()["bed"] is None


def test_last_bed_cannot_be_held_twice(client, db, auth):
    asha, coord = auth("WORKER"), auth("COORDINATOR")
    set_beds(client, db, coord, KALYANI, "GENERAL", 10, 9)
    assert try_referral(client, db, asha, phone="9876500002").status_code == 201
    assert try_referral(client, db, asha, phone="9876500003").json()["error"]["code"] == "NO_BEDS_AVAILABLE"


def test_reject_releases_the_bed_and_no_beds_marks_ward_full(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    r = post(client, f"/referrals/{ref['id']}/reject", staff, {"reason": "NO_BEDS"})
    assert r.json()["bed"]["status"] == "RELEASED"
    w = ward(client, asha, db)
    assert (w["held"], w["free"], w["occupied"]) == (0, 0, 10)  # the hospital told us it is full


def test_arrival_turns_the_hold_into_an_occupied_bed(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha, triage="EMERGENCY")
    held_until = ref["bed"]["held_until"]
    accepted = post(client, f"/referrals/{ref['id']}/accept", staff).json()
    assert accepted["bed"]["held_until"] > held_until  # accepting extends the hold until arrival
    arrived = post(client, f"/referrals/{ref['id']}/arrival", staff).json()
    assert arrived["bed"]["status"] == "OCCUPIED"
    w = ward(client, asha, db)
    assert (w["held"], w["occupied"], w["free"]) == (0, 7, 3)


def test_pass_scan_also_occupies_the_bed(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    qr = client.get(f"{API}/referrals/{ref['id']}/pass", headers=asha).json()["qr_text"]
    r = post(client, "/referral-passes/verify", staff, {"qr_text": qr})
    assert r.json()["referral"]["bed"]["status"] == "OCCUPIED"


def test_unused_hold_expires_and_suggests_another_hospital(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha, triage="EMERGENCY")  # held for 1 hour
    assert run_watchdog(db)["bed_holds_expired"] == 0
    result = run_watchdog(db, now=utcnow() + timedelta(hours=2))
    db.commit()
    assert result["bed_holds_expired"] == 1
    assert db.scalar(select(BedHold.status).where(BedHold.referral_id == ref["id"])) == "EXPIRED"
    alert = db.scalar(select(Notification).where(Notification.kind == "BED_HOLD_EXPIRED",
                                                 Notification.user_id == db.scalar(
                                                     select(User.id).where(User.email == "asha@sahyogcare.test"))))
    assert "Suggested instead:" in alert.message
    assert ward(client, asha, db)["held"] == 0


# ---------- keeping bed counts current ----------


def test_who_may_update_beds(client, db, auth):
    staff, coord, asha = auth("FACILITY_STAFF"), auth("COORDINATOR"), auth("WORKER")
    url = f"{API}/facilities/{facility_id(db)}/beds/GENERAL"
    assert client.put(url, headers=staff, json={"total": 12, "occupied": 5}).status_code == 200
    assert client.put(url, headers=coord, json={"total": 12, "occupied": 6}).status_code == 200
    assert client.put(url, headers=asha, json={"total": 12, "occupied": 6}).status_code == 403
    other = headers_of(db, "staff.ranaghat@sahyogcare.test")
    assert client.put(url, headers=other, json={"total": 12, "occupied": 6}).status_code == 403
    assert client.put(url, headers=staff, json={"total": 5, "occupied": 6}).status_code == 422


def test_counts_must_leave_room_for_held_beds(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    make_referral(client, db, asha)
    r = client.put(f"{API}/facilities/{facility_id(db)}/beds/GENERAL", headers=staff, json={"total": 10, "occupied": 10})
    assert r.status_code == 422 and r.json()["error"]["code"] == "BEDS_HELD"


def test_staff_can_open_a_new_ward(client, db, auth):
    staff = auth("FACILITY_STAFF")
    r = client.put(f"{API}/facilities/{facility_id(db)}/beds/ICU", headers=staff, json={"total": 2, "occupied": 0})
    assert any(w["ward"] == "ICU" and w["free"] == 2 for w in r.json()["wards"])


def test_coordinator_adds_a_hospital(client, db, auth):
    coord = auth("COORDINATOR")
    body = {"name": "Krishnanagar Test Hospital", "type": "District Hospital", "latitude": 23.4, "longitude": 88.5,
            "has_ambulance": True, "services": ["General Medicine", "Emergency"],
            "wards": [{"ward": "GENERAL", "total": 20, "occupied": 5}]}
    r = client.post(f"{API}/facilities", headers=coord, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["district"] == "Nadia" and r.json()["wards"][0]["free"] == 15
    assert client.post(f"{API}/facilities", headers=coord, json=body).json()["error"]["code"] == "DUPLICATE_FACILITY"
    assert client.post(f"{API}/facilities", headers=auth("WORKER"), json=body).status_code == 403

    r = client.patch(f"{API}/facilities/{facility_id(db, HARINGHATA)}", headers=coord,
                     json={"has_ambulance": True, "add_services": ["Paediatrics"]})
    assert r.json()["has_ambulance"] and "Paediatrics" in [s["service"] for s in r.json()["services"]]


# ---------- recommendation ----------


def test_recommendation_prefers_free_beds_and_explains_itself(client, db, auth):
    asha, coord = auth("WORKER"), auth("COORDINATOR")
    set_beds(client, db, coord, KALYANI, "GENERAL", 10, 10)
    recs = client.get(f"{API}/facilities/recommend", headers=asha,
                      params={"service": "General Medicine", "limit": 50}).json()
    assert len(recs) == 11  # 4 demo + 7 real hospitals offer General Medicine
    assert recs[-1]["facility_name"] == KALYANI and recs[-1]["beds_free"] == 0
    assert "General ward full" in recs[-1]["reasons"]
    assert all(r["beds_free"] > 0 for r in recs[:3])  # hospitals with free beds come first
    assert recs[0]["score"] >= recs[1]["score"] >= recs[2]["score"]


def test_recommendation_uses_distance(client, db, auth):
    asha = auth("WORKER")
    near_haringhata = {"service": "General Medicine", "latitude": 22.96, "longitude": 88.57}
    recs = client.get(f"{API}/facilities/recommend", headers=asha, params=near_haringhata).json()
    assert recs[0]["facility_name"] == HARINGHATA and recs[0]["distance_km"] < 2


def test_unavailable_service_is_ranked_down(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    post(client, f"/referrals/{ref['id']}/reject", staff, {"reason": "NO_DOCTOR_AVAILABLE"})
    recs = client.get(f"{API}/facilities/recommend", headers=asha,
                      params={"service": "General Medicine", "limit": 50}).json()
    assert recs[-1]["facility_name"] == KALYANI and recs[-1]["service_availability"] == "UNAVAILABLE"


# ---------- re-routing ----------


def test_reroute_moves_the_patient_and_the_bed(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    old = make_referral(client, db, asha)
    alts = client.get(f"{API}/referrals/{old['id']}/alternatives", headers=asha).json()
    assert KALYANI not in [a["facility_name"] for a in alts]

    r = post(client, f"/referrals/{old['id']}/reroute", asha, {"destination_facility_id": alts[0]["facility_id"]})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["rerouted_from_code"] == old["code"] and new["bed"]["status"] == "HELD"
    assert new["facility"]["id"] == alts[0]["facility_id"] and new["code"] != old["code"]

    old_now = client.get(f"{API}/referrals/{old['id']}", headers=asha).json()
    assert old_now["status"] == "REROUTED" and not old_now["is_open"]
    assert old_now["bed"]["status"] == "RELEASED" and old_now["rerouted_to_code"] == new["code"]
    assert ward(client, asha, db)["held"] == 0

    # The first hospital is told the patient is no longer coming, and cannot act on it.
    staff_id = db.scalar(select(User.id).where(User.email == "staff@sahyogcare.test"))
    assert db.scalar(select(Notification.id).where(Notification.user_id == staff_id,
                                                   Notification.kind == "REFERRAL_WITHDRAWN"))
    assert post(client, f"/referrals/{old['id']}/accept", staff).status_code == 409

    # Re-routing again is not possible, and the next suggestions skip every hospital tried.
    again = post(client, f"/referrals/{old['id']}/reroute", asha, {"destination_facility_id": alts[1]["facility_id"]})
    assert again.json()["error"]["code"] == "ALREADY_REROUTED"
    tried = {KALYANI, new["facility"]["name"]}
    alts2 = client.get(f"{API}/referrals/{new['id']}/alternatives", headers=asha).json()
    assert not tried & {a["facility_name"] for a in alts2}


def test_reroute_after_rejection(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    old = make_referral(client, db, asha)
    post(client, f"/referrals/{old['id']}/reject", staff, {"reason": "NO_BEDS"})
    r = post(client, f"/referrals/{old['id']}/reroute", asha, {"destination_facility_id": facility_id(db, RANAGHAT)})
    assert r.status_code == 201
    assert client.get(f"{API}/referrals/{old['id']}", headers=asha).json()["status"] == "REJECTED"


def test_coordinator_can_reroute_for_the_asha(client, db, auth):
    asha, coord = auth("WORKER"), auth("COORDINATOR")
    old = make_referral(client, db, asha)
    r = post(client, f"/referrals/{old['id']}/reroute", coord, {"destination_facility_id": facility_id(db, NADIA)})
    assert r.status_code == 201
    # The ASHA still owns the new referral and gets its updates.
    assert r.json()["id"] in [x["id"] for x in client.get(f"{API}/referrals", headers=asha).json()]


def test_cannot_reroute_after_arrival_or_to_same_hospital(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    same = post(client, f"/referrals/{ref['id']}/reroute", asha, {"destination_facility_id": facility_id(db)})
    assert same.json()["error"]["code"] == "SAME_FACILITY"
    post(client, f"/referrals/{ref['id']}/accept", staff)
    post(client, f"/referrals/{ref['id']}/arrival", staff)
    r = post(client, f"/referrals/{ref['id']}/reroute", asha, {"destination_facility_id": facility_id(db, RANAGHAT)})
    assert r.status_code == 409


def test_reroute_to_a_full_hospital_offers_others(client, db, auth):
    asha, coord = auth("WORKER"), auth("COORDINATOR")
    set_beds(client, db, coord, RANAGHAT, "GENERAL", 6, 6)
    old = make_referral(client, db, asha)
    r = post(client, f"/referrals/{old['id']}/reroute", asha, {"destination_facility_id": facility_id(db, RANAGHAT)})
    assert r.json()["error"]["code"] == "NO_BEDS_AVAILABLE"
    names = {a["facility_name"] for a in r.json()["error"]["details"]["alternatives"]}
    assert not names & {KALYANI, RANAGHAT}
    # Nothing changed: the original referral and its bed are untouched.
    assert client.get(f"{API}/referrals/{old['id']}", headers=asha).json()["bed"]["status"] == "HELD"


def test_patient_lookup_follows_the_reroute(client, db, auth):
    asha = auth("WORKER")
    old = make_referral(client, db, asha)
    new = post(client, f"/referrals/{old['id']}/reroute", asha,
               {"destination_facility_id": facility_id(db, NADIA)}).json()
    r = client.post(f"{API}/public/referral-status", json={"code": old["code"], "phone_last4": "3210"}).json()
    assert r["status"] == "REROUTED" and r["rerouted_to_code"] == new["code"]
    assert r["rerouted_to_facility"] == NADIA and r["emergency_number"] == "108"


def test_reroute_works_offline(client, db, auth):
    asha = auth("WORKER")
    old = make_referral(client, db, asha)
    ops = [{"idempotency_key": "rr1", "type": "REROUTE",
            "payload": {"referral_id": old["id"], "destination_facility_id": facility_id(db, RANAGHAT)}}]
    first = post(client, "/sync/batch", asha, {"operations": ops}).json()["results"][0]
    assert first["status"] == "ok" and first["result"]["rerouted_from_code"] == old["code"]
    again = post(client, "/sync/batch", asha, {"operations": ops}).json()["results"][0]
    assert again["replayed"]
    assert db.scalar(select(BedWard.occupied).where(BedWard.facility_id == facility_id(db, RANAGHAT),
                                                    BedWard.ward == "GENERAL")) == 3
