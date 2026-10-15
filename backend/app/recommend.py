"""Which hospital should this patient go to? Ranks every hospital offering the service.

The ranking uses only what the system actually knows: free beds in the right
ward (and how recently they were confirmed), whether a recent rejection said
the service is not running, how often and how fast each hospital answered
recent referrals, and distance when both locations are known. The weights are
placeholders in app/rules.py. Every result explains itself in `reasons`, so
the ASHA can see why a hospital is suggested — the choice stays hers.
"""

import math
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import beds
from app.models import Facility, FacilityService, Referral
from app.rules import (
    PERFORMANCE_MIN_REFERRALS,
    PERFORMANCE_WINDOW,
    SCORE_BEDS_FREE,
    SCORE_FREE_BED_CAP,
    SCORE_NO_BEDS,
    SCORE_PER_FREE_BED,
    SCORE_PER_HOUR_TO_ACCEPT,
    SCORE_PER_KM,
    SCORE_REJECTION_RATE,
    SCORE_SERVICE_UNAVAILABLE,
    SCORE_STALE_BEDS,
    Status,
    ward_for_service,
)
from app.schemas import RecommendationOut
from app.timeutil import as_utc, utcnow


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance (haversine). Road distance is longer; this is for ranking only."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _performance(db: Session, facility_id: str, now: datetime) -> tuple[float | None, float | None]:
    """(rejection rate, average hours to accept) over recent referrals, or None when too few."""
    since = now - PERFORMANCE_WINDOW
    refs = list(db.scalars(
        select(Referral).where(Referral.destination_facility_id == facility_id, Referral.created_at >= since)
    ))
    accepted, rejected, hours = 0, 0, []
    for r in refs:
        for e in r.events:
            if e.to_status == Status.ACCEPTED:
                accepted += 1
                hours.append((as_utc(e.at) - as_utc(r.created_at)).total_seconds() / 3600)
            elif e.to_status == Status.REJECTED:
                rejected += 1
    decided = accepted + rejected
    if decided < PERFORMANCE_MIN_REFERRALS:
        return None, None
    return round(rejected / decided, 2), (round(sum(hours) / len(hours), 1) if hours else None)


def recommend(
    db: Session,
    service: str,
    district: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    exclude: set[str] | None = None,
    limit: int = 10,
) -> list[RecommendationOut]:
    now = utcnow()
    ward = ward_for_service(service)
    stmt = (
        select(Facility)
        .options(selectinload(Facility.services))
        .where(Facility.active.is_(True),
               Facility.services.any(func.lower(FacilityService.service) == service.strip().lower()))
    )
    if district:
        stmt = stmt.where(Facility.district.ilike(district))
    results: list[RecommendationOut] = []
    for f in db.scalars(stmt).unique():
        if exclude and f.id in exclude:
            continue
        svc = next(s for s in f.services if s.service.lower() == service.strip().lower())
        score, reasons = 0.0, []

        if svc.availability == "UNAVAILABLE":
            score += SCORE_SERVICE_UNAVAILABLE
            reasons.append(f"Recently reported: {svc.availability_note or 'service not available'}")
        elif svc.availability == "AVAILABLE":
            reasons.append(f"{svc.service} confirmed running recently")

        free = total = None
        updated_at, stale = None, False
        if ward is not None:
            state = beds.ward_state(db, f.id, ward)
            if state is None:
                reasons.append(f"No bed data for the {ward.lower()} ward")
            else:
                free, total = state.free, state.ward.total
                updated_at, stale = as_utc(state.ward.updated_at), state.stale(now)
                if free > 0:
                    score += SCORE_BEDS_FREE + SCORE_PER_FREE_BED * min(free, SCORE_FREE_BED_CAP)
                    reasons.append(f"{free} {ward.lower()} bed{'s' if free != 1 else ''} free")
                else:
                    score += SCORE_NO_BEDS
                    reasons.append(f"{ward.capitalize()} ward full")
                if stale:
                    score += SCORE_STALE_BEDS
                    reasons.append("Bed count not confirmed in the last 12 hours")

        rate, hours = _performance(db, f.id, now)
        if rate is not None:
            score += SCORE_REJECTION_RATE * rate
            if rate >= 0.3:
                reasons.append(f"Turned away {round(rate * 100)}% of recent referrals")
        if hours is not None:
            score += SCORE_PER_HOUR_TO_ACCEPT * min(hours, 24)
            reasons.append(f"Usually accepts in about {hours:g} h")

        dist = None
        if None not in (latitude, longitude, f.latitude, f.longitude):
            dist = round(distance_km(latitude, longitude, f.latitude, f.longitude), 1)
            score += SCORE_PER_KM * dist
            reasons.append(f"About {dist:g} km away (straight line)")

        if f.has_ambulance:
            reasons.append("Has its own ambulance")

        results.append(RecommendationOut(
            facility_id=f.id, facility_name=f.name, facility_type=f.type, phone=f.phone,
            service=svc.service, service_availability=svc.availability, ward=ward,
            beds_free=free, beds_total=total, beds_updated_at=updated_at, beds_stale=stale,
            distance_km=dist, rejection_rate=rate, average_hours_to_accept=hours,
            has_ambulance=f.has_ambulance, score=round(score, 1), reasons=reasons,
        ))
    results.sort(key=lambda r: (-r.score, r.facility_name))
    return results[:limit]

