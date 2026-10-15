"""Each area (Nadia, Naihati) is fully separate: its coordinator sees and approves only its own."""

from sqlalchemy import select

from app.models import Facility, User
from app.security import access_token_for
from test_referrals import API, facility_id, make_referral, post
from test_signup import sign_up

NAIHATI_SGH = "Naihati State General Hospital"


def naihati_coordinator(db):
    u = User(email="officer.naihati@gmail.com", name="Naihati officer", role="COORDINATOR", district="Naihati")
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {access_token_for(u)}"}


def names(client, h):
    return {f["name"] for f in client.get(f"{API}/facilities", headers=h).json()}


def test_each_area_sees_only_its_own_hospitals(client, db, auth):
    naihati = naihati_coordinator(db)
    assert names(client, naihati) == {NAIHATI_SGH}
    nadia = names(client, auth("WORKER"))
    assert NAIHATI_SGH not in nadia and "Chakdaha State General Hospital" in nadia
    # Asking for another area's hospital directly finds nothing.
    assert client.get(f"{API}/facilities/{facility_id(db)}", headers=naihati).status_code == 404
    assert client.get(f"{API}/facilities", headers=naihati, params={"district": "Nadia"}).json()[0]["district"] \
        == "Naihati"


def test_coordinator_cannot_touch_another_area(client, db, auth):
    naihati = naihati_coordinator(db)
    r = client.put(f"{API}/facilities/{facility_id(db)}/beds/GENERAL", headers=naihati, json={"total": 1, "occupied": 0})
    assert r.status_code == 403
    assert all(u["district"] == "Naihati" for u in client.get(f"{API}/users", headers=naihati).json())

    # A Nadia ASHA's referral is invisible to Naihati.
    ref = make_referral(client, db, auth("WORKER"))
    assert client.get(f"{API}/referrals", headers=naihati).json() == []
    assert client.get(f"{API}/referrals/{ref['id']}", headers=naihati).status_code == 404


def test_sign_up_goes_to_the_chosen_area(client, db, auth):
    naihati = naihati_coordinator(db)
    me, _ = sign_up(client, "nurse.naihati@gmail.com")
    assert client.get(f"{API}/public/districts").json() == ["Nadia", "Naihati"]
    sgh = db.scalar(select(Facility.id).where(Facility.name == NAIHATI_SGH))
    # The hospital list for the chosen area, then the request.
    listed = client.get(f"{API}/facilities", headers=me, params={"district": "naihati"}).json()
    assert [f["name"] for f in listed] == [NAIHATI_SGH]
    r = post(client, "/access-requests", me, {"role": "FACILITY_STAFF", "name": "Rita", "district": "naihati",
                                              "facility_id": sgh})
    assert r.status_code == 201, r.text

    # Only Naihati's coordinator sees and decides it.
    assert client.get(f"{API}/access-requests", headers=auth("COORDINATOR")).json() == []
    pending = client.get(f"{API}/access-requests", headers=naihati).json()
    assert [p["email"] for p in pending] == ["nurse.naihati@gmail.com"]
    assert post(client, f"/access-requests/{pending[0]['id']}/approve", auth("COORDINATOR")).status_code == 404
    assert post(client, f"/access-requests/{pending[0]['id']}/approve", naihati).status_code == 200
    assert client.get(f"{API}/me", headers=me).json()["district"] == "Naihati"


def test_unknown_area_and_cross_area_hospital_are_refused(client, db, auth):
    me, _ = sign_up(client, "someone@gmail.com")
    assert post(client, "/access-requests", me, {"role": "WORKER", "name": "X", "district": "Kolkata"}).status_code == 422
    # A Nadia hospital cannot be chosen while asking to join Naihati.
    r = post(client, "/access-requests", me, {"role": "DOCTOR", "name": "X", "district": "Naihati",
                                              "facility_id": facility_id(db)})
    assert r.status_code == 422


def test_asha_cannot_refer_outside_her_area(client, db, auth):
    asha = auth("WORKER")
    sgh = db.scalar(select(Facility.id).where(Facility.name == NAIHATI_SGH))
    p = post(client, "/patients", asha, {"name": "Rina", "age": 30, "phone": "9876500999", "consent_given": True}).json()
    e = post(client, f"/patients/{p['id']}/encounters", asha, {"reason": "Fever", "triage": "ROUTINE"}).json()
    r = post(client, "/referrals", asha, {"patient_id": p["id"], "encounter_id": e["id"],
                                          "destination_facility_id": sgh, "requested_service": "General Medicine"})
    assert r.status_code == 404
