"""Bed counts per hospital ward.

Free beds = total - occupied. (Step 2 adds beds held for referred patients.)
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BedWard
from app.rules import BED_DATA_STALE_AFTER
from app.timeutil import as_utc


@dataclass
class WardState:
    ward: BedWard

    @property
    def free(self) -> int:
        return max(0, self.ward.total - self.ward.occupied)

    def stale(self, now: datetime) -> bool:
        return now - as_utc(self.ward.updated_at) > BED_DATA_STALE_AFTER


def ward_state(db: Session, facility_id: str, ward: str) -> WardState | None:
    """Current counts for one ward, or None when the hospital has not reported that ward."""
    row = db.scalar(select(BedWard).where(BedWard.facility_id == facility_id, BedWard.ward == ward))
    return WardState(row) if row is not None else None


def states_for(db: Session, facility_id: str) -> list[WardState]:
    rows = db.scalars(select(BedWard).where(BedWard.facility_id == facility_id).order_by(BedWard.ward))
    return [WardState(r) for r in rows]
