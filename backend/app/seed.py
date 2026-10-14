"""Load starting data: facilities and test users. Safe to run more than once.

Run:  python -m app.seed

All people here are fake test accounts on the reserved .test domain.
Facility phone numbers are left empty on purpose: add real desk numbers
from the district health office rather than invented ones.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.db import SessionLocal
from app.models import BedWard, Facility, FacilityService, User
from app.rules import Role, Ward

DISTRICT = "Nadia"

# Same four facilities as the frontend's public/data/facilities.json.
FACILITIES = [
    ("Kalyani District Hospital", "District Hospital", 14, ["General Medicine", "Emergency", "Diagnostics"]),
    ("Ranaghat Community Health Centre", "CHC", 8, ["General Medicine", "Maternity"]),
    ("Nadia Sub-Divisional Hospital", "Sub-Divisional Hospital", 22, ["General Medicine", "Paediatrics", "Diagnostics"]),
    ("Haringhata Primary Health Centre", "PHC", 3, ["General Medicine", "Maternity"]),
]

# Approximate town-centre locations (latitude, longitude) and whether each has its own ambulance.
# Replace with exact values from the National Hospital Directory / ABDM registry.
LOCATIONS = {
    "Kalyani District Hospital": (22.975, 88.434, True),
    "Ranaghat Community Health Centre": (23.178, 88.564, True),
    "Nadia Sub-Divisional Hospital": (23.405, 88.490, True),
    "Haringhata Primary Health Centre": (22.958, 88.570, False),
}

# Starting bed counts per ward: (total, occupied). Test data only — staff or the
# coordinator replace them with real counts from the app.
WARDS = {
    "Kalyani District Hospital": {Ward.GENERAL: (10, 6), Ward.EMERGENCY: (4, 2)},
    "Ranaghat Community Health Centre": {Ward.GENERAL: (6, 3), Ward.MATERNITY: (4, 1)},
    "Nadia Sub-Divisional Hospital": {Ward.GENERAL: (12, 8), Ward.PAEDIATRIC: (6, 2)},
    "Haringhata Primary Health Centre": {Ward.GENERAL: (3, 1), Ward.MATERNITY: (2, 0)},
}

# (email, name, role, facility name or None)
USERS = [
    ("asha@sahyogcare.test", "Test ASHA", Role.WORKER, None),
    ("staff@sahyogcare.test", "Test Facility Staff", Role.FACILITY_STAFF, "Kalyani District Hospital"),
    ("doctor@sahyogcare.test", "Test Doctor", Role.DOCTOR, "Kalyani District Hospital"),
    ("coordinator@sahyogcare.test", "Test Coordinator", Role.COORDINATOR, None),
    ("staff.ranaghat@sahyogcare.test", "Test Staff Ranaghat", Role.FACILITY_STAFF, "Ranaghat Community Health Centre"),
    ("doctor.ranaghat@sahyogcare.test", "Test Doctor Ranaghat", Role.DOCTOR, "Ranaghat Community Health Centre"),
    ("staff.nadia@sahyogcare.test", "Test Staff Nadia SDH", Role.FACILITY_STAFF, "Nadia Sub-Divisional Hospital"),
    ("doctor.nadia@sahyogcare.test", "Test Doctor Nadia SDH", Role.DOCTOR, "Nadia Sub-Divisional Hospital"),
    ("staff.haringhata@sahyogcare.test", "Test Staff Haringhata", Role.FACILITY_STAFF,
     "Haringhata Primary Health Centre"),
    ("doctor.haringhata@sahyogcare.test", "Test Doctor Haringhata", Role.DOCTOR, "Haringhata Primary Health Centre"),
]


def seed(db: Session) -> dict[str, int]:
    added = {"facilities": 0, "users": 0, "wards": 0}
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

    for name, (lat, lng, ambulance) in LOCATIONS.items():
        f = by_name.get(name)
        if f is not None and f.latitude is None:
            f.latitude, f.longitude, f.has_ambulance = lat, lng, ambulance

    # Wards are only added where missing, so counts staff have updated are never overwritten.
    have = {(w.facility_id, w.ward) for w in db.scalars(select(BedWard))}
    for name, wards in WARDS.items():
        f = by_name.get(name)
        if f is None:
            continue
        for ward, (total, occupied) in wards.items():
            if (f.id, ward) not in have:
                db.add(BedWard(facility_id=f.id, ward=ward, total=total, occupied=occupied))
                added["wards"] += 1

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
    from app.migrate import run_migrations

    run_migrations()
    with SessionLocal() as session:
        result = seed(session)
    print(f"Added {result['facilities']} facilities, {result['wards']} wards and {result['users']} users.")
