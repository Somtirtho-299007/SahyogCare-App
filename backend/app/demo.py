"""A live story of re-routing, on a throwaway database. Your real data is never touched.

Run from the backend folder:   python -m app.demo

It fills Kalyani's general ward, sends an emergency referral there, shows the
system refusing to hold a bed that does not exist and suggesting the next best
hospital, re-routes the patient, sends that hospital's ambulance, and follows
the patient until the bed is occupied.
"""

import os
import sys
import tempfile
from pathlib import Path

DEMO_DB = Path(tempfile.gettempdir()) / "sahyogcare_demo.db"
os.environ["SAHYOG_DATABASE_URL"] = f"sqlite:///{DEMO_DB}"
os.environ["SAHYOG_ENVIRONMENT"] = "development"
os.environ["SAHYOG_WATCHDOG_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Facility, User  # noqa: E402
from app.security import access_token_for  # noqa: E402
from app.seed import seed  # noqa: E402

API = "/api/v1"
KALYANI = "Kalyani District Hospital"


def say(step: str, text: str) -> None:
    print(f"\n[{step}] {text}")


def main() -> int:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        users = {u.email.split("@")[0]: u for u in db.scalars(select(User))}
        facilities = {f.name: f.id for f in db.scalars(select(Facility))}
        h = {name: {"Authorization": f"Bearer {access_token_for(u)}"} for name, u in users.items()}

    with TestClient(app) as c:
        def call(method, path, who, body=None, ok=(200, 201)):
            r = c.request(method, f"{API}{path}", headers=h[who], json=body)
            if r.status_code not in ok:
                raise SystemExit(f"Unexpected answer {r.status_code} from {path}: {r.text}")
            return r.json()

        say("1", "Coordinator (district office) reports Kalyani's general ward as full: 10 of 10 beds.")
        call("PUT", f"/facilities/{facilities[KALYANI]}/beds/GENERAL", "coordinator", {"total": 10, "occupied": 10})

        say("2", "ASHA registers Rina (SpO2 88%) and marks the visit EMERGENCY.")
        p = call("POST", "/patients", "asha", {"name": "Rina Das", "age": 34, "sex": "F", "phone": "9876543210",
                                                "consent_given": True})
        e = call("POST", f"/patients/{p['id']}/encounters", "asha",
                 {"reason": "Breathlessness since morning", "triage": "EMERGENCY", "vitals": {"spo2": 88, "pulse": 118}})
        if e.get("triage_suggestion"):
            print(f"    Server hint: {e['triage_suggestion']}")

        say("3", "ASHA tries to refer her to Kalyani for General Medicine.")
        refused = c.post(f"{API}/referrals", headers=h["asha"], json={
            "patient_id": p["id"], "encounter_id": e["id"], "destination_facility_id": facilities[KALYANI],
            "requested_service": "General Medicine"}).json()["error"]
        print(f"    Refused: {refused['code']} - {refused['message']}")
        print("    Suggested instead:")
        for a in refused["details"]["alternatives"]:
            print(f"      - {a['facility_name']}: score {a['score']} | " + "; ".join(a["reasons"]))

        say("4", "The ASHA has no other option nearby today, so she sends Rina to Kalyani anyway (no bed held).")
        ref = call("POST", "/referrals", "asha", {
            "patient_id": p["id"], "encounter_id": e["id"], "destination_facility_id": facilities[KALYANI],
            "requested_service": "General Medicine", "allow_without_bed": True})
        print(f"    Referral {ref['code']} created; bed held: {ref['bed'] is not None}")

        say("5", "Kalyani rejects: no beds.")
        call("POST", f"/referrals/{ref['id']}/reject", "staff", {"reason": "NO_BEDS"})

        say("6", "ASHA asks for the best alternatives and re-routes with one tap.")
        alts = call("GET", f"/referrals/{ref['id']}/alternatives", "asha")
        best = alts[0]
        print(f"    Best: {best['facility_name']} ({best['beds_free']} free beds)")
        new = call("POST", f"/referrals/{ref['id']}/reroute", "asha", {"destination_facility_id": best["facility_id"]})
        print(f"    New referral {new['code']} (continues {new['rerouted_from_code']}); "
              f"bed {new['bed']['status']} until {new['bed']['held_until'][:16]} UTC")

        staff = {facilities[n]: k for k, n in [("staff", KALYANI), ("staff.ranaghat", "Ranaghat Community Health Centre"),
                                                ("staff.nadia", "Nadia Sub-Divisional Hospital"),
                                                ("staff.haringhata", "Haringhata Primary Health Centre")]}
        desk = staff[best["facility_id"]]

        if best["has_ambulance"]:
            say("7", f"ASHA requests {best['facility_name']}'s ambulance; the hospital sends it (and so accepts).")
            call("POST", f"/referrals/{new['id']}/ambulance", "asha", {"pickup_note": "Chakdaha, near the Shiv temple"})
            sent = call("POST", f"/referrals/{new['id']}/ambulance/dispatch", desk,
                        {"eta_minutes": 25, "vehicle_number": "WB-52-1234", "driver_phone": "9800011122"})
            print(f"    Status {sent['status']}; ambulance {sent['ambulance']['status']}, "
                  f"expected {sent['ambulance']['expected_at'][:16]} UTC")
        else:
            say("7", f"{best['facility_name']} has no ambulance: the app shows 'Call 108'. The hospital accepts.")
            call("POST", f"/referrals/{new['id']}/accept", desk)

        say("8", "Patient arrives; the held bed becomes an occupied bed.")
        arrived = call("POST", f"/referrals/{new['id']}/arrival", desk)
        print(f"    Bed {arrived['bed']['status']}"
              + (f"; ambulance {arrived['ambulance']['status']}" if arrived["ambulance"] else ""))

        say("9", "Rina's family checks with the OLD code and is pointed to the new one.")
        pub = c.post(f"{API}/public/referral-status", json={"code": ref["code"], "phone_last4": "3210"}).json()
        print(f"    {pub['code']}: {pub['status']} -> now {pub['rerouted_to_code']} at {pub['rerouted_to_facility']}")

        say("10", "ASHA's alerts:")
        for n in call("GET", "/notifications", "asha"):
            print(f"    - {n['message']}")

    engine.dispose()
    DEMO_DB.unlink(missing_ok=True)
    print("\nDemo finished. Nothing was saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
