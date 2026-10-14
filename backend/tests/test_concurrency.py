"""Two people pressing the same button at the same moment (needs PostgreSQL for real row locks).

Run with SAHYOG_TEST_DATABASE_URL=postgresql+psycopg://... ; skipped on SQLite, which has no row locks.
"""

import threading

import pytest
from sqlalchemy import func, select

from app.db import engine
from app.models import BedHold, BedWard, ReferralEvent
from test_beds import headers_of
from test_referrals import API, KALYANI, facility_id, make_encounter, make_patient, make_referral, new_user

pytestmark = pytest.mark.skipif(engine.dialect.name != "postgresql", reason="row locks need PostgreSQL")


def together(calls):
    """Start every call at the same instant; return their responses."""
    gate, out = threading.Barrier(len(calls)), [None] * len(calls)

    def run(i, fn):
        gate.wait()
        out[i] = fn()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def _accept_in_own_session(referral_id, email):
    """Call the real endpoint code with its own database session, like two separate requests."""
    from app.db import SessionLocal
    from app.errors import ApiError
    from app.models import User
    from app.routers.referrals import accept

    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.email == email))
        try:
            accept(referral_id, None, user, s)
            return "OK"
        except ApiError as e:
            s.rollback()
            return e.code


def test_two_staff_accept_the_same_referral_at_once(client, db, auth, monkeypatch):
    import time

    from app import workflow

    # Make each request slow between reading the status and saving the change, so the two
    # really overlap (without the row lock both would then pass the check).
    real_check = workflow.check_transition

    def slow_check(*args):
        time.sleep(0.3)
        return real_check(*args)

    monkeypatch.setattr(workflow, "check_transition", slow_check)
    asha = auth("WORKER")
    ref = make_referral(client, db, asha)
    new_user(db, "staff2@sahyogcare.test", "FACILITY_STAFF", facility=KALYANI)
    codes = sorted(together([lambda e=e: _accept_in_own_session(ref["id"], e)
                             for e in ("staff@sahyogcare.test", "staff2@sahyogcare.test")]))
    # One wins; the other waits for the lock, then sees "already accepted" (a clear answer,
    # not a database clash).
    assert codes == ["INVALID_STATE_TRANSITION", "OK"], codes
    db.expire_all()
    accepted = db.scalar(select(func.count(ReferralEvent.id)).where(ReferralEvent.referral_id == ref["id"],
                                                                   ReferralEvent.to_status == "ACCEPTED"))
    assert accepted == 1


def test_two_ashas_book_the_last_bed_at_once(client, db, auth):
    kalyani = facility_id(db, KALYANI)
    ward = db.scalar(select(BedWard).where(BedWard.facility_id == kalyani, BedWard.ward == "GENERAL"))
    ward.total, ward.occupied = 1, 0  # exactly one free bed
    db.commit()
    a, b = auth("WORKER"), new_user(db, "asha2@sahyogcare.test", "WORKER")
    bodies = []
    for h, phone in ((a, "9000000011"), (b, "9000000012")):
        p = make_patient(client, h, name=f"P{phone[-2:]}", phone=phone)
        e = make_encounter(client, h, p["id"])
        bodies.append((h, {"patient_id": p["id"], "encounter_id": e["id"], "destination_facility_id": kalyani,
                           "requested_service": "General Medicine"}))
    answers = together([lambda h=h, body=body: client.post(f"{API}/referrals", headers=h, json=body)
                        for h, body in bodies])
    codes = sorted(r.status_code for r in answers)
    assert codes == [201, 409], codes
    loser = next(r for r in answers if r.status_code == 409).json()["error"]
    assert loser["code"] == "NO_BEDS_AVAILABLE"
    db.expire_all()
    assert db.scalar(select(func.count(BedHold.id)).where(BedHold.status == "HELD")) == 1
