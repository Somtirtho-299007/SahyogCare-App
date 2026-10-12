"""Load starting data: facilities and test users. Safe to run more than once.

Run:  python -m app.seed

All people here are fake test accounts on the reserved .test domain.
Facility phone numbers are left empty on purpose: add real desk numbers
from the district health office rather than invented ones.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db import Base, SessionLocal, engine
from app.models import Facility, FacilityService, User
from app.rules import Role

DISTRICT = "Nadia"

# Same four facilities as the frontend's public/data/facilities.json.
FACILITIES = [
    ("Kalyani District Hospital", "District Hospital", 14, ["General Medicine", "Emergency", "Diagnostics"]),
    ("Ranaghat Community Health Centre", "CHC", 8, ["General Medicine", "Maternity"]),
    ("Nadia Sub-Divisional Hospital", "Sub-Divisional Hospital", 22, ["General Medicine", "Paediatrics", "Diagnostics"]),
    ("Haringhata Primary Health Centre", "PHC", 3, ["General Medicine", "Maternity"]),
]

# (email, name, role, facility name or None)
USERS = [
    ("asha@sahyogcare.test", "Test ASHA", Role.WORKER, None),
    ("staff@sahyogcare.test", "Test Facility Staff", Role.FACILITY_STAFF, "Kalyani District Hospital"),
    ("doctor@sahyogcare.test", "Test Doctor", Role.DOCTOR, "Kalyani District Hospital"),
    ("coordinator@sahyogcare.test", "Test Coordinator", Role.COORDINATOR, None),
]


def seed(db: Session) -> dict[str, int]:
    added = {"facilities": 0, "users": 0}
    by_name: dict[str, Facility] = {f.name: f for f in db.scalars(select(Facility))}

    for name, ftype, beds, services in FACILITIES:
        if name in by_name:
            continue
        f = Facility(name=name, type=ftype, district=DISTRICT, beds=beds)
        f.services = [FacilityService(service=s) for s in services]
        db.add(f)
        by_name[name] = f
        added["facilities"] += 1
    db.flush()

    existing = set(db.scalars(select(User.email)))
    for email, name, role, facility in USERS:
        if email in existing:
            continue
        db.add(
            User(
                email=email,
                name=name,
                role=role,
                district=DISTRICT,
                facility_id=by_name[facility].id if facility else None,
            )
        )
        added["users"] += 1

    db.commit()
    return added


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        result = seed(session)
    print(f"Added {result['facilities']} facilities and {result['users']} users.")
