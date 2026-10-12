from datetime import timedelta

from sqlalchemy import func, select

from app.models import Patient, Referral
from app.timeutil import utcnow
from test_referrals import API, facility_id, make_referral, post


def offline_queue(db):
    """What an ASHA's phone would queue while offline: patient → visit → referral."""
    return [
        {"idempotency_key": "p1", "type": "CREATE_PATIENT",
         "payload": {"name": "Offline Patient", "age": 40, "phone": "9123456780", "consent_given": True}},
        {"idempotency_key": "e1", "type": "CREATE_ENCOUNTER",
         "payload": {"patient_id": "$ref:p1", "reason": "Chest pain", "triage": "EMERGENCY",
                     "vitals": {"pulse": 120}}},
        {"idempotency_key": "r1", "type": "CREATE_REFERRAL",
         "payload": {"patient_id": "$ref:p1", "encounter_id": "$ref:e1",
                     "destination_facility_id": facility_id(db), "requested_service": "Emergency"}},
    ]


def test_offline_queue_syncs_in_one_go_and_only_once(client, db, auth):
    asha = auth("WORKER")
    ops = offline_queue(db)
    first = post(client, "/sync/batch", asha, {"operations": ops}).json()["results"]
    assert [r["status"] for r in first] == ["ok", "ok", "ok"]
    referral = first[2]["result"]
    assert referral["status"] == "CREATED" and referral["triage"] == "EMERGENCY"
    assert referral["patient"]["id"] == first[0]["result"]["id"]

    # The phone did not hear back and sends the same queue again.
    again = post(client, "/sync/batch", asha, {"operations": ops}).json()["results"]
    assert all(r["status"] == "ok" and r["replayed"] for r in again)
    assert again[2]["result"]["id"] == referral["id"]
    assert db.scalar(select(func.count()).select_from(Patient)) == 1
    assert db.scalar(select(func.count()).select_from(Referral)) == 1

    # A later batch can refer to something created in an earlier one.
    later = post(client, "/sync/batch", asha, {"operations": [
        {"idempotency_key": "e2", "type": "CREATE_ENCOUNTER",
         "payload": {"patient_id": "$ref:p1", "reason": "Review", "triage": "ROUTINE"}},
    ]}).json()["results"]
    assert later[0]["status"] == "ok" and later[0]["result"]["patient_id"] == first[0]["result"]["id"]


def test_one_bad_action_does_not_block_the_rest(client, db, auth):
    asha = auth("WORKER")
    ops = offline_queue(db)
    ops.insert(0, {"idempotency_key": "bad", "type": "CREATE_PATIENT",
                   "payload": {"name": "X", "age": 30, "phone": "123", "consent_given": True}})
    ops.append({"idempotency_key": "ghost", "type": "CREATE_ENCOUNTER",
                "payload": {"patient_id": "$ref:never", "reason": "x", "triage": "ROUTINE"}})
    results = post(client, "/sync/batch", asha, {"operations": ops}).json()["results"]
    assert [r["status"] for r in results] == ["error", "ok", "ok", "ok", "error"]
    assert results[0]["error"]["code"] == "VALIDATION_ERROR" and "phone" in str(results[0]["error"]["details"])
    assert results[-1]["error"]["code"] == "UNKNOWN_REFERENCE"


def test_offline_status_change_that_conflicts(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    post(client, f"/referrals/{ref['id']}/reject", staff, {"reason": "NO_BEDS"})  # done online first

    # Meanwhile another desk phone had queued an "accept" while offline.
    r = post(client, "/sync/batch", staff, {"operations": [
        {"idempotency_key": "a1", "type": "ACCEPT", "payload": {"referral_id": ref["id"]}},
    ]}).json()["results"][0]
    assert r["status"] == "error" and r["error"]["code"] == "SYNC_CONFLICT"
    assert r["error"]["details"]["current_status"] == "REJECTED"


def test_sync_respects_roles(client, db, auth):
    asha, doctor = auth("WORKER"), auth("DOCTOR")
    ref = make_referral(client, db, asha)
    results = post(client, "/sync/batch", asha, {"operations": [
        {"idempotency_key": "x1", "type": "ACCEPT", "payload": {"referral_id": ref["id"]}},
    ]}).json()["results"]
    assert results[0]["error"]["code"] == "FORBIDDEN"
    results = post(client, "/sync/batch", doctor, {"operations": offline_queue(db)[:1]}).json()["results"]
    assert results[0]["error"]["code"] == "FORBIDDEN"


def test_offline_desk_scan_syncs(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    qr = client.get(f"{API}/referrals/{ref['id']}/pass", headers=asha).json()["qr_text"]
    scanned = (utcnow() + timedelta(seconds=30)).isoformat()
    r = post(client, "/sync/batch", staff, {"operations": [
        {"idempotency_key": "s1", "type": "SCAN_PASS", "payload": {"qr_text": qr, "scanned_at": scanned}},
    ]}).json()["results"][0]
    assert r["status"] == "ok" and r["result"]["referral"]["status"] == "ARRIVAL_RECORDED"
    assert r["result"]["referral"]["events"][-1]["source"] == "OFFLINE_PASS"


def test_changes_since_cursor(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    first = client.get(f"{API}/sync/changes", headers=asha).json()
    assert [r["id"] for r in first["referrals"]] == [ref["id"]]

    cursor = first["cursor"]
    assert client.get(f"{API}/sync/changes", headers=asha, params={"since": cursor}).json()["referrals"] == []

    post(client, f"/referrals/{ref['id']}/accept", staff)
    later = client.get(f"{API}/sync/changes", headers=asha, params={"since": cursor}).json()
    assert [r["status"] for r in later["referrals"]] == ["ACCEPTED"]
    assert [n["kind"] for n in later["notifications"]] == ["STATUS_ACCEPTED"]
