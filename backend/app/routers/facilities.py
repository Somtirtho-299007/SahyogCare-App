"""Hospitals: search, live bed counts, and hospital management.

Any logged-in user may search hospitals and see bed counts. Hospital staff keep
their own hospital's bed counts up to date. The coordinator (acting for the
district health office) may add hospitals and correct any hospital's data.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import beds
from app.db import get_db
from app.errors import ApiError
from app.models import AuditLog, BedWard, Facility, FacilityService, User
from app.rules import AVAILABILITY_STALE_AFTER, Role
from app.schemas import (
    FacilityIn,
    FacilityOut,
    FacilityUpdateIn,
    ServiceOut,
    Ward,
    WardIn,
    WardOut,
)
from app.security import current_user, current_user_any, require_roles
from app.timeutil import as_utc, utcnow
from app.workflow import commit

router = APIRouter(prefix="/facilities", tags=["facilities"])


def _facility_out(db: Session, f: Facility, now: datetime) -> FacilityOut:
    services = []
    for s in f.services:
        updated = as_utc(s.availability_updated_at)
        services.append(
            ServiceOut(
                service=s.service,
                availability=s.availability,
                availability_note=s.availability_note,
                availability_updated_at=updated,
                stale=updated is None or now - updated > AVAILABILITY_STALE_AFTER,
            )
        )
    wards = [
        WardOut(ward=st.ward.ward, total=st.ward.total, occupied=st.ward.occupied, free=st.free,
                updated_at=as_utc(st.ward.updated_at), stale=st.stale(now))
        for st in beds.states_for(db, f.id)
    ]
    return FacilityOut(
        id=f.id, name=f.name, type=f.type, district=f.district, phone=f.phone, beds=f.beds,
        latitude=f.latitude, longitude=f.longitude, has_ambulance=f.has_ambulance,
        services=services, wards=wards,
    )


def _rank(f: FacilityOut, service: str | None) -> int:
    """Facilities where the requested service is not known to be unavailable come first."""
    if not service:
        return 0
    match = next((s for s in f.services if s.service.lower() == service.lower()), None)
    return 1 if match and match.availability == "UNAVAILABLE" else 0


@router.get("", response_model=list[FacilityOut])
def search_facilities(
    q: str | None = Query(None, max_length=80, description="Matches name, type or service"),
    service: str | None = Query(None, max_length=80, description="Only facilities listing this service"),
    district: str | None = Query(None, max_length=80),
    # Hospital names are not private; people waiting for approval need them to pick their hospital.
    _: User = Depends(current_user_any),
    db: Session = Depends(get_db),
) -> list[FacilityOut]:
    stmt = select(Facility).options(selectinload(Facility.services)).order_by(Facility.name)
    if district:
        stmt = stmt.where(Facility.district.ilike(district))
    if service:
        stmt = stmt.where(Facility.services.any(FacilityService.service.ilike(service)))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Facility.name.ilike(like),
                Facility.type.ilike(like),
                Facility.services.any(FacilityService.service.ilike(like)),
            )
        )
    now = utcnow()
    results = [_facility_out(db, f, now) for f in db.scalars(stmt).unique()]
    return sorted(results, key=lambda f: _rank(f, service))


@router.get("/{facility_id}", response_model=FacilityOut)
def get_facility(facility_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> FacilityOut:
    return _facility_out(db, _get(db, facility_id), utcnow())


def _get(db: Session, facility_id: str) -> Facility:
    f = db.get(Facility, facility_id, options=[selectinload(Facility.services)])
    if f is None:
        raise ApiError(404, "NOT_FOUND", "Facility not found.")
    return f


def _check_can_manage(user: User, f: Facility) -> None:
    """Staff manage their own hospital; the coordinator manages hospitals in their district."""
    if user.role == Role.FACILITY_STAFF and user.facility_id == f.id:
        return
    if user.role == Role.COORDINATOR and f.district.lower() == user.district.lower():
        return
    raise ApiError(403, "FORBIDDEN", "You cannot change this hospital's data.")


def _set_ward(db: Session, f: Facility, ward: str, counts: WardIn, user: User) -> None:
    if counts.occupied > counts.total:
        raise ApiError(422, "VALIDATION_ERROR", "Occupied beds cannot be more than total beds.",
                       {"fields": {"occupied": "More than total"}})
    row = db.scalar(select(BedWard).where(BedWard.facility_id == f.id, BedWard.ward == ward))
    if row is None:
        row = BedWard(facility_id=f.id, ward=ward)
        db.add(row)
    row.total, row.occupied, row.updated_at, row.updated_by_id = counts.total, counts.occupied, utcnow(), user.id
    db.add(AuditLog(actor_id=user.id, action=f"BEDS_UPDATED_{ward}", target_type="facility", target_id=f.id))


@router.put("/{facility_id}/beds/{ward}", response_model=FacilityOut)
def update_beds(facility_id: str, ward: Ward, body: WardIn,
                user: User = Depends(require_roles(Role.FACILITY_STAFF, Role.COORDINATOR)),
                db: Session = Depends(get_db)) -> FacilityOut:
    """Report the current bed count for one ward. Re-sending the same numbers confirms they are still right."""
    f = _get(db, facility_id)
    _check_can_manage(user, f)
    _set_ward(db, f, ward, body, user)
    commit(db)
    return _facility_out(db, f, utcnow())


@router.post("", response_model=FacilityOut, status_code=201)
def create_facility(body: FacilityIn, user: User = Depends(require_roles(Role.COORDINATOR)),
                    db: Session = Depends(get_db)) -> FacilityOut:
    """Add a hospital to the coordinator's district."""
    exists_already = db.scalar(select(Facility.id).where(
        func.lower(Facility.name) == body.name.strip().lower(), func.lower(Facility.district) == user.district.lower()
    ))
    if exists_already:
        raise ApiError(409, "DUPLICATE_FACILITY", "A hospital with this name already exists in your district.",
                       {"facility_id": exists_already})
    f = Facility(name=body.name.strip(), type=body.type.strip(), district=user.district, phone=body.phone,
                 latitude=body.latitude, longitude=body.longitude, has_ambulance=body.has_ambulance, hfr_id=body.hfr_id)
    names = {s.strip().lower(): s.strip() for s in body.services}
    f.services = [FacilityService(service=s) for s in names.values()]
    db.add(f)
    db.flush()
    for w in body.wards:
        _set_ward(db, f, w.ward, w, user)
    db.add(AuditLog(actor_id=user.id, action="FACILITY_CREATED", target_type="facility", target_id=f.id))
    commit(db)
    return _facility_out(db, _get(db, f.id), utcnow())


@router.patch("/{facility_id}", response_model=FacilityOut)
def update_facility(facility_id: str, body: FacilityUpdateIn, user: User = Depends(require_roles(Role.COORDINATOR)),
                    db: Session = Depends(get_db)) -> FacilityOut:
    f = _get(db, facility_id)
    _check_can_manage(user, f)
    for field in ("phone", "latitude", "longitude", "has_ambulance"):
        value = getattr(body, field)
        if value is not None:
            setattr(f, field, value)
    have = {s.service.lower() for s in f.services}
    for s in body.add_services:
        if s.strip().lower() not in have:
            f.services.append(FacilityService(service=s.strip()))
            have.add(s.strip().lower())
    db.add(AuditLog(actor_id=user.id, action="FACILITY_UPDATED", target_type="facility", target_id=f.id))
    commit(db)
    return _facility_out(db, _get(db, f.id), utcnow())
