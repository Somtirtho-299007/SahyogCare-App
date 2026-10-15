"""Ambulance trips: the receiving hospital's ambulance fetching a referred patient."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AmbulanceTrip, Referral
from app.rules import AMBULANCE_OPEN, AmbulanceStatus
from app.timeutil import as_utc, utcnow


def latest_trip(db: Session, referral: Referral) -> AmbulanceTrip | None:
    return db.scalar(
        select(AmbulanceTrip).where(AmbulanceTrip.referral_id == referral.id)
        .order_by(AmbulanceTrip.requested_at.desc()).limit(1)
    )


def open_trip(db: Session, referral: Referral) -> AmbulanceTrip | None:
    trip = latest_trip(db, referral)
    return trip if trip is not None and trip.status in AMBULANCE_OPEN else None


def expected_at(trip: AmbulanceTrip):
    if trip.dispatched_at is None or trip.eta_minutes is None:
        return None
    return as_utc(trip.dispatched_at) + timedelta(minutes=trip.eta_minutes)


def cancel_open(db: Session, referral: Referral, reason: str) -> bool:
    trip = open_trip(db, referral)
    if trip is None:
        return False
    trip.status, trip.cancel_reason, trip.ended_at = AmbulanceStatus.CANCELLED, reason, utcnow()
    return True


def complete_on_arrival(db: Session, referral: Referral) -> None:
    trip = open_trip(db, referral)
    if trip is not None:
        trip.status, trip.ended_at = AmbulanceStatus.COMPLETED, utcnow()
        trip.picked_up_at = trip.picked_up_at or trip.ended_at
