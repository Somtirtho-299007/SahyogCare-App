from datetime import timedelta

from sqlalchemy import select

from app.models import AmbulanceTrip, Notification, User
from app.timeutil import utcnow
from app.watchdog import run_watchdog
from test_beds import HARINGHATA, NADIA, headers_of
from test_referrals import API, facility_id, make_referral, post

PICKUP = {"pickup_note": "Village Chakdaha, near the Shiv temple, blue house"}


def asha_alerts(db, kind):
    asha_id = db.scalar(select(User.id).where(User.email == "asha@sahyogcare.test"))
    return list(db.scalars(select(Notification.message).where(Notification.user_id == asha_id,
                                                              Notification.kind == kind)))


def test_ambulance_journey(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha, triage="EMERGENCY")
    rid = ref["id"]

    r = post(client, f"/referrals/{rid}/ambulance", asha, PICKUP)
    assert r.status_code == 201 and r.json()["ambulance"]["status"] == "REQUESTED"
    assert post(client, f"/referrals/{rid}/ambulance", asha, PICKUP).json()["error"]["code"] == "AMBULANCE_ALREADY_REQUESTED"

    # Sending the ambulance also accepts the referral.
    r = post(client, f"/referrals/{rid}/ambulance/dispatch", staff,
             {"eta_minutes": 25, "vehicle_number": "WB-52-1234", "driver_phone": "9800011122"})
    body = r.json()
    assert body["status"] == "ACCEPTED" and body["ambulance"]["status"] == "DISPATCHED"
    assert body["ambulance"]["expected_at"] is not None
    assert any("about 25 min" in m for m in asha_alerts(db, "AMBULANCE_DISPATCHED"))

    assert post(client, f"/referrals/{rid}/ambulance/picked-up", asha).json()["ambulance"]["status"] == "PICKED_UP"
    arrived = post(client, f"/referrals/{rid}/arrival", staff).json()
    assert arrived["ambulance"]["status"] == "COMPLETED" and arrived["bed"]["status"] == "OCCUPIED"

    # The patient sees the ambulance on the public status page.
    pub = client.post(f"{API}/public/referral-status", json={"code": ref["code"], "phone_last4": "3210"}).json()
    assert pub["ambulance"]["vehicle_number"] == "WB-52-1234"


def test_hospital_without_ambulance_points_to_108(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha, facility=HARINGHATA)
    r = post(client, f"/referrals/{ref['id']}/ambulance", asha, PICKUP)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "NO_HOSPITAL_AMBULANCE" and r.json()["error"]["details"]["call"] == "108"


def test_only_the_receiving_hospital_dispatches(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    post(client, f"/referrals/{ref['id']}/ambulance", asha, PICKUP)
    other = headers_of(db, "staff.nadia@sahyogcare.test")
    assert post(client, f"/referrals/{ref['id']}/ambulance/dispatch", other, {"eta_minutes": 10}).status_code == 404
    assert post(client, f"/referrals/{ref['id']}/ambulance/dispatch", asha, {"eta_minutes": 10}).status_code == 403


def test_staff_cancel_tells_the_asha_to_call_108(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    post(client, f"/referrals/{ref['id']}/ambulance", asha, PICKUP)
    r = post(client, f"/referrals/{ref['id']}/ambulance/cancel", staff, {"reason": "Vehicle under repair"})
    assert r.json()["ambulance"]["status"] == "CANCELLED"
    assert any("Call 108" in m for m in asha_alerts(db, "AMBULANCE_CANCELLED"))


def test_reroute_cancels_the_ambulance(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    post(client, f"/referrals/{ref['id']}/ambulance", asha, PICKUP)
    post(client, f"/referrals/{ref['id']}/reroute", asha, {"destination_facility_id": facility_id(db, NADIA)})
    old = client.get(f"{API}/referrals/{ref['id']}", headers=asha).json()
    assert old["ambulance"]["status"] == "CANCELLED"


def test_watchdog_flags_ambulance_not_sent(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha, triage="EMERGENCY")
    post(client, f"/referrals/{ref['id']}/ambulance", asha, PICKUP)
    assert run_watchdog(db)["ambulance_alerts"] == 0
    result = run_watchdog(db, now=utcnow() + timedelta(minutes=20))
    db.commit()
    assert result["ambulance_alerts"] == 1 and result["coordinator_alerts"] >= 1
    assert any("Call 108 now" in m for m in asha_alerts(db, "WATCH_AMBULANCE_NOT_SENT"))


def test_watchdog_flags_late_ambulance(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    post(client, f"/referrals/{ref['id']}/ambulance", asha, PICKUP)
    post(client, f"/referrals/{ref['id']}/ambulance/dispatch", staff, {"eta_minutes": 20, "driver_phone": "9800011122"})
    assert run_watchdog(db, now=utcnow() + timedelta(minutes=40))["ambulance_alerts"] == 0
    result = run_watchdog(db, now=utcnow() + timedelta(minutes=60))
    db.commit()
    assert result["ambulance_alerts"] == 1
    assert any("9800011122" in m for m in asha_alerts(db, "WATCH_AMBULANCE_LATE"))
    assert db.scalar(select(AmbulanceTrip.status)) == "DISPATCHED"


def test_ambulance_works_offline(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha)
    r = post(client, "/sync/batch", asha, {"operations": [
        {"idempotency_key": "a1", "type": "REQUEST_AMBULANCE", "payload": {"referral_id": ref["id"], **PICKUP}}]})
    assert r.json()["results"][0]["status"] == "ok"
    r = post(client, "/sync/batch", staff, {"operations": [
        {"idempotency_key": "d1", "type": "DISPATCH_AMBULANCE", "payload": {"referral_id": ref["id"], "eta_minutes": 15}}]})
    assert r.json()["results"][0]["result"]["ambulance"]["status"] == "DISPATCHED"
