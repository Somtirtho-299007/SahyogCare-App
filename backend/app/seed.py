"""Load starting data. Safe to run more than once; never overwrites what users changed.

Run:  python -m app.seed

1. Real government hospitals of Nadia district, copied from the district's
   official website. Only what the source says is filled in (name, type, address,
   PIN code, phone). Bed counts, location and ambulance are left empty: hospital
   staff or the coordinator enter them in the app.
2. Demo data (only when SAHYOG_DEMO_DATA is true, the default for development and
   tests): four test hospitals with made-up beds, and fake @sahyogcare.test accounts.
   With SAHYOG_DEMO_DATA=false (the live server), the demo hospitals are hidden and
   the demo accounts switched off.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.config import settings
from app.db import SessionLocal
from app.models import BedWard, Facility, FacilityService, User
from app.rules import Role, Ward

DISTRICT = "Nadia"

NADIA_SOURCE = "nadia.gov.in, Public Utilities: Hospitals (accessed Oct 2026)"

# Real hospitals: (name, type, address, PIN code, phone), exactly as listed by the
# district. Each starts with General Medicine; the coordinator adds the other
# services each hospital really offers. Add the rest of the district's list in the
# app (Coordinator > Hospitals > Add hospital) or here.
REAL_FACILITIES = [
    ("Chakdaha State General Hospital", "State General Hospital",
     "Chakdaha Sukhsagar Road, Near Sampriti Mancha, Chakdaha, Nadia", "741222", "7548975218"),
    ("Aranghata Rural Hospital", "Rural Hospital (BPHC)", "Aranghata, Sabdalpur, Nadia", "741501", "9153217447"),
    ("Bagula Rural Hospital", "Rural Hospital", "Bagula, Nadia", "741502", "7548975230"),
    ("Bethuadahari Rural Hospital", "Rural Hospital", "Bethuadahari, Nadia", "741126", "7548975225"),
    ("Bishnupur Rural Hospital", "Rural Hospital", "Bishnupur, P.O. Nadia Bishnupur, Nadia", "741103", "03472-229224"),
    ("Fulia Block Primary Health Centre", "Block Primary Health Centre", "Fulia, Nadia", "741402", "9333414373"),
    ("Chapra Rural Hospital", "Rural Hospital", "Bangaljhi, Chapra, Nadia", "741123", "7548975223"),
]

# Naihati (North 24 Parganas). Only what could be confirmed from public sources is
# filled in; the Naihati coordinator adds phone numbers and the other hospitals in the app.
NAIHATI = "Naihati"
NAIHATI_SOURCE = "Government hospital (DNB-accredited); contact details to be added by the Naihati coordinator"
NAIHATI_FACILITIES = [
    ("Naihati State General Hospital", "State General Hospital", "Naihati, North 24 Parganas", None, None),
]
REAL_DEFAULT_SERVICES = ["General Medicine"]

# ---------- Demo data (made up; never shown on the live server) ----------

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

    real = [(DISTRICT, NADIA_SOURCE, *row) for row in REAL_FACILITIES] + \
           [(NAIHATI, NAIHATI_SOURCE, *row) for row in NAIHATI_FACILITIES]
    for district, source, name, ftype, address, pincode, phone in real:
        if name in by_name:
            continue
        f = Facility(name=name, type=ftype, district=district, address=address, pincode=pincode, phone=phone,
                     source=source)
        f.services = [FacilityService(service=s) for s in REAL_DEFAULT_SERVICES]
        db.add(f)
        by_name[name] = f
        added["facilities"] += 1
    db.flush()

    if not settings.demo_data:
        _hide_demo(db, by_name)
        db.commit()
        return added

    for name, ftype, beds, services in FACILITIES:
        if name in by_name:
            continue
        f = Facility(name=name, type=ftype, district=DISTRICT, beds=beds, source="Demo data (made up)")
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


def _hide_demo(db: Session, by_name: dict[str, Facility]) -> None:
    for name, *_ in FACILITIES:
        if name in by_name:
            by_name[name].active = False
    for email, *_ in USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.is_active = False


if __name__ == "__main__":
    from app.migrate import run_migrations

    run_migrations()
    with SessionLocal() as session:
        result = seed(session)
    print(f"Added {result['facilities']} facilities, {result['wards']} wards and {result['users']} users.")
