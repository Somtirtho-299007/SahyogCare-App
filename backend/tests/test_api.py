from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Facility, FacilityService, User
from app.seed import seed


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_seed_is_repeatable(db):
    assert seed(db) == {"facilities": 0, "users": 0, "wards": 0}
    assert len(db.scalars(select(Facility)).all()) == 12  # 7 real Nadia + 1 Naihati + 4 demo
    assert {u.role for u in db.scalars(select(User))} == {"WORKER", "FACILITY_STAFF", "DOCTOR", "COORDINATOR"}


def test_facility_search(client, auth):
    h = auth("WORKER")
    names = [f["name"] for f in client.get("/api/v1/facilities", headers=h).json()]
    assert len(names) == 11 and "Chakdaha State General Hospital" in names

    maternity = client.get("/api/v1/facilities", headers=h, params={"service": "maternity"}).json()
    assert {f["type"] for f in maternity} == {"CHC", "PHC"}

    by_text = client.get("/api/v1/facilities", headers=h, params={"q": "paediatrics"}).json()
    assert [f["name"] for f in by_text] == ["Nadia Sub-Divisional Hospital"]

    # Approved users always see their own area, whatever they ask for.
    other = client.get("/api/v1/facilities", headers=h, params={"district": "Naihati"}).json()
    assert {f["district"] for f in other} == {"Nadia"}


def test_unknown_availability_is_stale(client, auth):
    h = auth("DOCTOR")
    f = client.get("/api/v1/facilities", headers=h).json()[0]
    assert all(s["availability"] == "UNKNOWN" and s["stale"] for s in f["services"])


def test_unavailable_service_is_ranked_last(client, db, auth):
    h = auth("WORKER")
    chc = db.scalar(select(Facility).where(Facility.type == "CHC"))
    svc = db.scalar(
        select(FacilityService).where(FacilityService.facility_id == chc.id, FacilityService.service == "Maternity")
    )
    svc.availability = "UNAVAILABLE"
    svc.availability_note = "No doctor available"
    svc.availability_updated_at = datetime.now(timezone.utc)
    db.commit()

    results = client.get("/api/v1/facilities", headers=h, params={"service": "Maternity"}).json()
    assert results[-1]["id"] == chc.id
    last = next(s for s in results[-1]["services"] if s["service"] == "Maternity")
    assert last["availability"] == "UNAVAILABLE" and last["stale"] is False


def test_errors_use_the_standard_shape(client, auth):
    h = auth("WORKER")
    r = client.get("/api/v1/facilities/does-not-exist", headers=h)
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND" and err["request_id"]

    r = client.get("/api/v1/nothing-here")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"

    r = client.get("/api/v1/facilities", headers=h, params={"q": "x" * 200})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_facilities_need_login(client):
    r = client.get("/api/v1/facilities")
    assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_root_redirects_to_docs(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/docs"


def test_real_hospitals_carry_their_source(client, auth):
    h = auth("WORKER")
    chakdaha = next(f for f in client.get("/api/v1/facilities", headers=h).json()
                    if f["name"] == "Chakdaha State General Hospital")
    assert chakdaha["pincode"] == "741222" and chakdaha["phone"] == "7548975218"
    assert chakdaha["source"].startswith("nadia.gov.in")
    assert chakdaha["wards"] == []  # no invented bed numbers


def test_live_server_hides_demo_data(client, db, auth, monkeypatch):
    from app.config import settings

    from app.security import access_token_for

    monkeypatch.setattr(settings, "demo_data", False)
    seed(db)
    real = User(email="officer@gmail.com", name="Officer", role="COORDINATOR", district="Nadia")
    db.add(real)
    db.commit()
    h = {"Authorization": f"Bearer {access_token_for(real)}"}
    names = [f["name"] for f in client.get("/api/v1/facilities", headers=h).json()]
    assert len(names) == 7 and "Kalyani District Hospital" not in names
    asha = db.scalar(select(User).where(User.email == "asha@sahyogcare.test"))
    assert asha.is_active is False
