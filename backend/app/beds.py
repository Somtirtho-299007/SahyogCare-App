"""Bed reservation: counting free beds and holding one for each referred patient.

A bed is held the moment a referral is created, kept while the hospital
accepts and the patient travels, turned into an occupied bed on arrival, and
given back automatically when the referral is rejected, sent elsewhere, or
nobody acts in time (see app/watchdog.py).

Free beds = total - occupied - beds held for incoming referrals.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BedHold, BedWard, Referral
from app.rules import (
    BED_DATA_STALE_AFTER,
    HOLD_UNTIL_ACCEPTED,
    HOLD_UNTIL_ARRIVED,
    HoldStatus,
    Triage,
    ward_for_service,
)
from app.timeutil import as_utc, utcnow


@dataclass
class WardState:
    ward: BedWard
    held: int

    @property
    def free(self) -> int:
        return max(0, self.ward.total - self.ward.occupied - self.held)

    def stale(self, now: datetime) -> bool:
        return now - as_utc(self.ward.updated_at) > BED_DATA_STALE_AFTER


def held_count(db: Session, facility_id: str, ward: str) -> int:
    db.flush()  # count holds placed or released earlier in this same request
    return db.scalar(
        select(func.count()).select_from(BedHold).where(
            BedHold.facility_id == facility_id, BedHold.ward == ward, BedHold.status == HoldStatus.HELD
        )
    ) or 0


def ward_state(db: Session, facility_id: str, ward: str, lock: bool = False) -> WardState | None:
    """Current counts for one ward, or None when the hospital has not reported that ward."""
    stmt = select(BedWard).where(BedWard.facility_id == facility_id, BedWard.ward == ward)
    if lock:
        # PostgreSQL: two ASHAs booking the last bed at the same moment cannot both get it.
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        return None
    return WardState(row, held_count(db, facility_id, ward))


def states_for(db: Session, facility_id: str) -> list[WardState]:
    rows = db.scalars(select(BedWard).where(BedWard.facility_id == facility_id).order_by(BedWard.ward))
    return [WardState(r, held_count(db, facility_id, r.ward)) for r in rows]


def active_hold(db: Session, referral: Referral) -> BedHold | None:
    return db.scalar(select(BedHold).where(BedHold.referral_id == referral.id, BedHold.status == HoldStatus.HELD))


def hold_for(db: Session, referral: Referral) -> BedHold | None:
    return db.scalar(select(BedHold).where(BedHold.referral_id == referral.id))


def place_hold(db: Session, referral: Referral, state: WardState) -> BedHold:
    hold = BedHold(
        referral_id=referral.id,
        facility_id=referral.destination_facility_id,
        ward=state.ward.ward,
        status=HoldStatus.HELD,
        held_until=utcnow() + HOLD_UNTIL_ACCEPTED[Triage(referral.triage)],
    )
    db.add(hold)
    return hold


def extend_on_accept(db: Session, referral: Referral) -> None:
    """Accepting confirms the booking; the bed now waits for the patient to arrive."""
    hold = active_hold(db, referral)
    if hold is not None:
        hold.held_until = utcnow() + HOLD_UNTIL_ARRIVED[Triage(referral.triage)]


def release(db: Session, referral: Referral, reason: str, status: HoldStatus = HoldStatus.RELEASED) -> bool:
    hold = active_hold(db, referral)
    if hold is None:
        return False
    hold.status, hold.release_reason, hold.ended_at = status, reason, utcnow()
    return True


def occupy(db: Session, referral: Referral) -> None:
    """The patient arrived: the held bed becomes an occupied bed."""
    hold = active_hold(db, referral)
    ward_name = hold.ward if hold else ward_for_service(referral.requested_service)
    if hold is not None:
        hold.status, hold.ended_at = HoldStatus.OCCUPIED, utcnow()
    if ward_name is None:
        return
    state = ward_state(db, referral.destination_facility_id, ward_name, lock=True)
    if state is not None:
        state.ward.occupied = min(state.ward.total, state.ward.occupied + 1)


def mark_ward_full(db: Session, referral: Referral) -> None:
    """A "no beds" rejection is the freshest bed report we can get: no bed is free in that ward now."""
    ward_name = ward_for_service(referral.requested_service)
    if ward_name is None:
        return
    state = ward_state(db, referral.destination_facility_id, ward_name, lock=True)
    if state is None:
        return
    state.ward.occupied = max(state.ward.occupied, state.ward.total - state.held)
    state.ward.updated_at = utcnow()
    state.ward.updated_by_id = None  # learned from the rejection, not typed in


def expired_holds(db: Session, now: datetime) -> list[BedHold]:
    return [
        h for h in db.scalars(select(BedHold).where(BedHold.status == HoldStatus.HELD))
        if as_utc(h.held_until) < now
    ]
