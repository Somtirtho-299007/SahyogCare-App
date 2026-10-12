"""Facility search.

NOTE: these endpoints are public in step 1 so the frontend can be connected
early. Step 2 (login and roles) puts them behind authentication, as
docs/API_SPEC.md requires.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.errors import ApiError
from app.models import Facility, FacilityService
from app.rules import AVAILABILITY_STALE_AFTER
from app.schemas import FacilityOut, ServiceOut

router = APIRouter(prefix="/facilities", tags=["facilities"])


def _as_utc(dt: datetime | None) -> datetime | None:
    # SQLite returns naive datetimes; treat stored values as UTC.
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _facility_out(f: Facility, now: datetime) -> FacilityOut:
    services = []
    for s in f.services:
        updated = _as_utc(s.availability_updated_at)
        services.append(
            ServiceOut(
                service=s.service,
                availability=s.availability,
                availability_note=s.availability_note,
                availability_updated_at=updated,
                stale=updated is None or now - updated > AVAILABILITY_STALE_AFTER,
            )
        )
    return FacilityOut(
        id=f.id, name=f.name, type=f.type, district=f.district, phone=f.phone, beds=f.beds, services=services
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
    now = datetime.now(timezone.utc)
    results = [_facility_out(f, now) for f in db.scalars(stmt).unique()]
    return sorted(results, key=lambda f: _rank(f, service))


@router.get("/{facility_id}", response_model=FacilityOut)
def get_facility(facility_id: str, db: Session = Depends(get_db)) -> FacilityOut:
    f = db.get(Facility, facility_id, options=[selectinload(Facility.services)])
    if f is None:
        raise ApiError(404, "NOT_FOUND", "Facility not found.")
    return _facility_out(f, datetime.now(timezone.utc))
