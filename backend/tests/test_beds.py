"""Bed counts per hospital ward (step 1).

Seeded beds (see app/seed.py):
  Kalyani     GENERAL 10 total / 6 occupied (4 free), EMERGENCY 4 / 2
  Ranaghat    GENERAL 6 / 3, MATERNITY 4 / 1
  Nadia SDH   GENERAL 12 / 8, PAEDIATRIC 6 / 2
  Haringhata  GENERAL 3 / 1, MATERNITY 2 / 0
"""

from sqlalchemy import select

from app.models import User
from app.security import access_token_for
from test_referrals import API, KALYANI, facility_id

HARINGHATA = "Haringhata Primary Health Centre"


def ward(client, h, db, name=KALYANI, ward_name="GENERAL"):
    f = client.get(f"{API}/facilities/{facility_id(db, name)}", headers=h).json()
    return next(w for w in f["wards"] if w["ward"] == ward_name)


def headers_of(db, email):
    return {"Authorization": f"Bearer {access_token_for(db.scalar(select(User).where(User.email == email)))}"}


def test_hospitals_show_their_beds(client, db, auth):
    w = ward(client, auth("WORKER"), db)
    assert (w["total"], w["occupied"], w["free"], w["stale"]) == (10, 6, 4, False)


def test_every_hospital_has_staff_and_a_doctor(db):
    emails = set(db.scalars(select(User.email)))
    for town in ("ranaghat", "nadia", "haringhata"):
        assert f"staff.{town}@sahyogcare.test" in emails and f"doctor.{town}@sahyogcare.test" in emails


def test_who_may_update_beds(client, db, auth):
    staff, coord, asha = auth("FACILITY_STAFF"), auth("COORDINATOR"), auth("WORKER")
    url = f"{API}/facilities/{facility_id(db)}/beds/GENERAL"
    assert client.put(url, headers=staff, json={"total": 12, "occupied": 5}).status_code == 200
    assert ward(client, asha, db)["free"] == 7
    assert client.put(url, headers=coord, json={"total": 12, "occupied": 6}).status_code == 200
    assert client.put(url, headers=asha, json={"total": 12, "occupied": 6}).status_code == 403
    other = headers_of(db, "staff.ranaghat@sahyogcare.test")
    assert client.put(url, headers=other, json={"total": 12, "occupied": 6}).status_code == 403
    assert client.put(url, headers=staff, json={"total": 5, "occupied": 6}).status_code == 422


def test_staff_can_open_a_new_ward(client, db, auth):
    r = client.put(f"{API}/facilities/{facility_id(db)}/beds/ICU", headers=auth("FACILITY_STAFF"),
                   json={"total": 2, "occupied": 0})
    assert any(w["ward"] == "ICU" and w["free"] == 2 for w in r.json()["wards"])


def test_coordinator_adds_and_edits_a_hospital(client, db, auth):
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
