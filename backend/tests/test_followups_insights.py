from datetime import timedelta

from sqlalchemy import select

from app.models import FollowUp, Notification, Referral, User
from app.timeutil import utcnow
from app.watchdog import run_watchdog
from test_beds import headers_of
from test_referrals import API, make_referral, new_user, post


def age_referral(db, rid, **delta):
    r = db.get(Referral, rid)
    db.refresh(r)
    shift = timedelta(**delta)
    r.created_at = r.created_at - shift
    for e in r.events:
        e.at = e.at - shift
    db.commit()


def kinds_for(db, email):
    uid = db.scalar(select(User.id).where(User.email == email))
    db.expire_all()
    return [n.kind for n in db.scalars(select(Notification).where(Notification.user_id == uid))]


# ---------- watchdog ----------


def test_watchdog_flags_referrals_nobody_accepts(client, db, auth):
    asha = auth("WORKER")
    ref = make_referral(client, db, asha, triage="EMERGENCY", service="Emergency")

    assert run_watchdog(db)["not_accepted"] == 0  # just created: nothing to say
    age_referral(db, ref["id"], minutes=90)  # Emergency limit is 1 hour
    result = run_watchdog(db)
    db.commit()
    assert result["not_accepted"] == 1 and result["coordinator_alerts"] == 0
    assert kinds_for(db, "asha@sahyogcare.test").count("WATCH_NOT_ACCEPTED") == 1

    # Running again does not repeat the alert.
    assert run_watchdog(db)["not_accepted"] == 0

    # Twice the limit: the coordinator is told too.
    age_referral(db, ref["id"], hours=1)
    assert run_watchdog(db)["coordinator_alerts"] == 1
    db.commit()
    assert "WATCH_NOT_ACCEPTED" in kinds_for(db, "coordinator@sahyogcare.test")


def test_watchdog_flags_patients_who_never_arrive(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    ref = make_referral(client, db, asha, triage="PRIORITY")
    post(client, f"/referrals/{ref['id']}/accept", staff)
    age_referral(db, ref["id"], hours=25)  # Priority: 24 hours to arrive
    assert run_watchdog(db)["not_arrived"] == 1
    db.commit()
    msg = db.scalar(select(Notification.message).where(Notification.kind == "WATCH_NOT_ARRIVED"))
    assert "has not arrived" in msg


def test_overdue_follow_up_then_late_completion(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    rid = make_referral(client, db, asha)["id"]
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor)):
        post(client, f"/referrals/{rid}/{path}", h)
    post(client, f"/referrals/{rid}/outcome", doctor, {"follow_up_days": 2})

    fu_list = client.get(f"{API}/follow-ups", headers=asha).json()
    assert len(fu_list) == 1 and fu_list[0]["status"] == "DUE" and not fu_list[0]["is_late"]

    result = run_watchdog(db, now=utcnow() + timedelta(days=3))
    db.commit()
    assert result["follow_ups_overdue"] == 1 and result["coordinator_alerts"] == 1
    r = client.get(f"{API}/referrals/{rid}", headers=asha).json()
    assert r["status"] == "OVERDUE" and r["events"][-1]["source"] == "SYSTEM"

    # The coordinator sees it in the district list.
    assert client.get(f"{API}/follow-ups", headers=auth("COORDINATOR")).json()[0]["status"] == "OVERDUE"

    # The checkup happens late at the hospital: the hospital confirms it, and that still completes it.
    done = post(client, f"/follow-ups/{fu_list[0]['id']}/complete", doctor, {"note": "Seen, recovering"}).json()
    assert done["status"] == "COMPLETED" and done["referral_status"] == "CLOSED"
    assert client.get(f"{API}/follow-ups", headers=asha).json() == []


def test_missed_follow_up_and_escalation(client, db, auth):
    asha, staff, doctor, coord = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR"), auth("COORDINATOR")
    rid = make_referral(client, db, asha)["id"]
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor), ("outcome", doctor)):
        post(client, f"/referrals/{rid}/{path}", h)
    fid = client.get(f"{API}/follow-ups", headers=asha).json()[0]["id"]

    assert post(client, f"/follow-ups/{fid}/miss", asha, {"note": "House locked"}).json()["status"] == "OVERDUE"
    assert post(client, f"/referrals/{rid}/escalate", asha).status_code == 403  # only the coordinator
    r = post(client, f"/referrals/{rid}/escalate", coord, {"note": "Calling family"}).json()
    assert r["status"] == "ESCALATED" and r["follow_up"]["status"] == "ESCALATED"
    assert "STATUS_ESCALATED" in kinds_for(db, "asha@sahyogcare.test")
    assert post(client, f"/referrals/{rid}/close", coord).json()["status"] == "CLOSED"


def test_follow_ups_are_private(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    rid = make_referral(client, db, asha)["id"]
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor), ("outcome", doctor)):
        post(client, f"/referrals/{rid}/{path}", h)
    other = new_user(db, "asha9@sahyogcare.test", "WORKER")
    assert client.get(f"{API}/follow-ups", headers=other).json() == []
    fid = client.get(f"{API}/follow-ups", headers=asha).json()[0]["id"]
    assert post(client, f"/follow-ups/{fid}/sent", other).status_code == 404
    # A hospital sees only the checkups due at its own hospital.
    assert [f["id"] for f in client.get(f"{API}/follow-ups", headers=staff).json()] == [fid]
    other_staff = headers_of(db, "staff.nadia@sahyogcare.test")
    assert client.get(f"{API}/follow-ups", headers=other_staff).json() == []
    assert post(client, f"/follow-ups/{fid}/complete", other_staff).status_code == 404


def test_asha_sends_patient_and_only_the_hospital_confirms(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    rid = make_referral(client, db, asha)["id"]
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor), ("outcome", doctor)):
        post(client, f"/referrals/{rid}/{path}", h)
    fid = client.get(f"{API}/follow-ups", headers=asha).json()[0]["id"]

    # The ASHA sends the patient back for the checkup; the hospital desk is told to expect them.
    sent = post(client, f"/follow-ups/{fid}/sent", asha, {"note": "Coming Monday morning"}).json()
    assert sent["sent_at"] is not None and sent["status"] == "DUE"
    staff_id = db.scalar(select(User.id).where(User.email == "staff@sahyogcare.test"))
    msgs = list(db.scalars(select(Notification.message).where(Notification.user_id == staff_id,
                                                               Notification.kind == "FOLLOW_UP_SENT")))
    assert msgs and "Coming Monday morning" in msgs[0]
    assert client.get(f"{API}/referrals/{rid}", headers=asha).json()["follow_up"]["sent_at"] is not None

    # The ASHA cannot mark the checkup done, by either route; the hospital and coordinator cannot "send".
    assert post(client, f"/follow-ups/{fid}/complete", asha).status_code == 403
    assert post(client, f"/referrals/{rid}/close", asha).status_code == 403
    assert post(client, f"/follow-ups/{fid}/sent", staff).status_code == 403

    # The hospital confirms the checkup, and the ASHA is told.
    done = post(client, f"/follow-ups/{fid}/complete", staff, {"note": "Checkup done, fine"}).json()
    assert done["status"] == "COMPLETED" and done["referral_status"] == "CLOSED"
    assert "STATUS_CLOSED" in kinds_for(db, "asha@sahyogcare.test")
    assert post(client, f"/follow-ups/{fid}/sent", asha).json()["error"]["code"] == "ALREADY_COMPLETED"


def test_follow_up_steps_work_offline(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    rid = make_referral(client, db, asha)["id"]
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor), ("outcome", doctor)):
        post(client, f"/referrals/{rid}/{path}", h)
    fid = client.get(f"{API}/follow-ups", headers=asha).json()[0]["id"]
    op = lambda key, kind: {"operations": [{"idempotency_key": key, "type": kind, "payload": {"follow_up_id": fid}}]}
    assert post(client, "/sync/batch", asha, op("f1", "SEND_FOLLOW_UP")).json()["results"][0]["status"] == "ok"
    assert post(client, "/sync/batch", asha, op("f2", "COMPLETE_FOLLOW_UP")).json()["results"][0]["status"] != "ok"
    assert post(client, "/sync/batch", staff, op("f3", "COMPLETE_FOLLOW_UP")).json()["results"][0]["status"] == "ok"


def test_watchdog_endpoint_is_for_coordinators(client, auth):
    assert post(client, "/watchdog/run", auth("WORKER")).status_code == 403
    r = post(client, "/watchdog/run", auth("COORDINATOR"))
    assert r.status_code == 200 and set(r.json()) == {"not_accepted", "not_arrived", "follow_ups_overdue", "coordinator_alerts",
                                              "bed_holds_expired", "ambulance_alerts", "courses_completed",
                                              "dose_reminders", "bed_update_reminders"}


# ---------- activity summary and dashboards ----------


def test_activity_summary(client, db, auth):
    asha, staff, doctor = auth("WORKER"), auth("FACILITY_STAFF"), auth("DOCTOR")
    a = make_referral(client, db, asha, name="A", phone="9000000001")["id"]
    b = make_referral(client, db, asha, name="B", phone="9000000002")["id"]
    make_referral(client, db, asha, name="C", phone="9000000003")
    post(client, f"/referrals/{b}/reject", staff, {"reason": "NO_BEDS"})
    for path, h in (("accept", staff), ("arrival", staff), ("consultation", doctor), ("outcome", doctor)):
        post(client, f"/referrals/{a}/{path}", h)
    fid = client.get(f"{API}/follow-ups", headers=asha).json()[0]["id"]
    post(client, f"/follow-ups/{fid}/complete", staff)

    s = client.get(f"{API}/me/activity-summary", headers=asha).json()
    assert (s["referrals_created"], s["referrals_completed"], s["referrals_rejected"],
            s["follow_ups_completed"], s["open_now"]) == (3, 1, 1, 1, 1)
    assert "not an official incentive claim" in s["note"]

    empty = client.get(f"{API}/me/activity-summary", headers=asha, params={"month": "2020-01"}).json()
    assert empty["referrals_created"] == 0
    assert client.get(f"{API}/me/activity-summary", headers=asha, params={"month": "2026-13"}).status_code == 422
    assert client.get(f"{API}/me/activity-summary", headers=staff).status_code == 403


def test_dashboard_counts_agree_across_roles(client, db, auth):
    asha, staff = auth("WORKER"), auth("FACILITY_STAFF")
    make_referral(client, db, asha, triage="EMERGENCY", service="Emergency", name="A", phone="9000000001")
    r2 = make_referral(client, db, asha, triage="ROUTINE", name="B", phone="9000000002")["id"]
    r3 = make_referral(client, db, asha, triage="PRIORITY", name="C", phone="9000000003")["id"]
    post(client, f"/referrals/{r2}/reject", staff, {"reason": "NO_BEDS"})
    post(client, f"/referrals/{r3}/accept", staff)

    worker_view = client.get(f"{API}/dashboard/summary", headers=asha).json()
    staff_view = client.get(f"{API}/dashboard/summary", headers=staff).json()
    for view in (worker_view, staff_view):
        assert view["open"] == 2  # the rejected one is not open
        assert view["open_by_triage"] == {"EMERGENCY": 1, "PRIORITY": 1, "ROUTINE": 0}
        assert view["awaiting_acceptance"] == 1
    assert worker_view["unread_notifications"] == 2 and worker_view["facilities"] is None

    coord = client.get(f"{API}/dashboard/summary", headers=auth("COORDINATOR")).json()
    kalyani = coord["facilities"][0]
    assert kalyani["referrals_received"] == 3 and kalyani["accepted"] == 1 and kalyani["rejected"] == 1
    assert kalyani["waiting_for_acceptance"] == 1 and kalyani["rejection_rate"] == 0.5
    assert kalyani["average_hours_to_accept"] is not None
