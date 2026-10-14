"""Dashboard numbers, the ASHA's monthly activity summary, and the watchdog trigger."""

import hmac
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import referral_scope
from app.config import settings
from app.db import get_db
from app.errors import ApiError
from app.models import Facility, FollowUp, Notification, Referral, User
from app.rules import Role, Status, is_open
from app.schemas import ActivitySummaryOut, DashboardOut, FacilityPerformance, WatchdogRunOut
from app.security import current_user, require_roles
from app.timeutil import as_utc, utcnow
from app.watchdog import run_watchdog

router = APIRouter(tags=["insights"])


def _month_bounds(month: str | None) -> tuple[str, datetime, datetime]:
    now = utcnow()
    if month is None:
        month = f"{now.year:04d}-{now.month:02d}"
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ApiError(422, "VALIDATION_ERROR", "Month must look like 2026-10.", {"fields": {"month": "YYYY-MM"}})
    year, mon = map(int, month.split("-"))
    start = datetime(year, mon, 1, tzinfo=timezone.utc)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=timezone.utc)
    return month, start, end


def _within(dt, start, end) -> bool:
    dt = as_utc(dt)
    return dt is not None and start <= dt < end


def _closed_at(r: Referral) -> datetime | None:
    times = [as_utc(e.at) for e in r.events if e.to_status == Status.CLOSED]
    return max(times) if times else None


@router.get("/me/activity-summary", response_model=ActivitySummaryOut)
def activity_summary(
    month: str | None = Query(None, description="YYYY-MM; defaults to this month"),
    user: User = Depends(require_roles(Role.WORKER)),
    db: Session = Depends(get_db),
) -> ActivitySummaryOut:
    month, start, end = _month_bounds(month)
    mine = list(db.scalars(select(Referral).where(Referral.created_by_id == user.id)))
    rejected = sum(
        1 for r in mine for e in r.events if e.to_status == Status.REJECTED and _within(e.at, start, end)
    )
    follow_ups = db.scalars(select(FollowUp).where(FollowUp.assigned_to_id == user.id, FollowUp.status == "COMPLETED"))
    return ActivitySummaryOut(
        month=month,
        referrals_created=sum(1 for r in mine if _within(r.created_at, start, end)),
        referrals_completed=sum(1 for r in mine if _within(_closed_at(r), start, end)),
        referrals_rejected=rejected,
        follow_ups_completed=sum(1 for f in follow_ups if _within(f.completed_at, start, end)),
        open_now=sum(1 for r in mine if is_open(r.status)),
    )


def _facility_performance(db: Session, referrals: list[Referral]) -> list[FacilityPerformance]:
    by_facility: dict[str, list[Referral]] = {}
    for r in referrals:
        by_facility.setdefault(r.destination_facility_id, []).append(r)
    out = []
    for fid, refs in by_facility.items():
        facility = db.get(Facility, fid)
        accept_hours, accepted, rejected = [], 0, 0
        for r in refs:
            for e in r.events:
                if e.to_status == Status.ACCEPTED:
                    accepted += 1
                    accept_hours.append((as_utc(e.at) - as_utc(r.created_at)).total_seconds() / 3600)
                elif e.to_status == Status.REJECTED:
                    rejected += 1
        decided = accepted + rejected
        out.append(
            FacilityPerformance(
                facility_id=fid,
                facility_name=facility.name,
                referrals_received=len(refs),
                accepted=accepted,
                rejected=rejected,
                waiting_for_acceptance=sum(1 for r in refs if r.status == Status.CREATED),
                average_hours_to_accept=round(sum(accept_hours) / len(accept_hours), 1) if accept_hours else None,
                rejection_rate=round(rejected / decided, 2) if decided else None,
            )
        )
    # Where referrals get stuck most comes first.
    return sorted(out, key=lambda f: (-(f.waiting_for_acceptance), -(f.rejection_rate or 0), f.facility_name))


@router.get("/dashboard/summary", response_model=DashboardOut)
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)) -> DashboardOut:
    _, start, end = _month_bounds(None)
    referrals = list(db.scalars(select(Referral).where(referral_scope(user))))
    open_refs = [r for r in referrals if is_open(r.status)]
    by_triage = {t: 0 for t in ("EMERGENCY", "PRIORITY", "ROUTINE")}
    for r in open_refs:
        by_triage[r.triage] = by_triage.get(r.triage, 0) + 1
    unread = db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    return DashboardOut(
        role=user.role,
        open=len(open_refs),
        open_by_triage=by_triage,
        awaiting_acceptance=sum(1 for r in referrals if r.status == Status.CREATED),
        follow_ups_due=sum(1 for r in referrals if r.status == Status.FOLLOW_UP_DUE),
        overdue=sum(1 for r in referrals if r.status in (Status.OVERDUE, Status.ESCALATED)),
        closed_this_month=sum(1 for r in referrals if _within(_closed_at(r), start, end)),
        unread_notifications=unread,
        facilities=_facility_performance(db, referrals) if user.role == Role.COORDINATOR else None,
    )


@router.post("/watchdog/tick", response_model=WatchdogRunOut)
def watchdog_tick(x_cron_secret: str = Header(""), db: Session = Depends(get_db)) -> WatchdogRunOut:
    """For an outside scheduler (e.g. a free cron service) when the watchdog is not run inside the server."""
    if not settings.cron_secret or not hmac.compare_digest(x_cron_secret.encode(), settings.cron_secret.encode()):
        raise ApiError(404, "NOT_FOUND", "Not found.")
    from app.db import SessionLocal
    from app.watchdog import run_once

    db.close()
    result = run_once(SessionLocal)
    return WatchdogRunOut(**(result or {"not_accepted": 0, "not_arrived": 0, "follow_ups_overdue": 0,
                                        "coordinator_alerts": 0}))


@router.post("/watchdog/run", response_model=WatchdogRunOut)
def watchdog_now(_: User = Depends(require_roles(Role.COORDINATOR)), db: Session = Depends(get_db)) -> WatchdogRunOut:
    """Run the watchdog immediately (it also runs by itself every few minutes)."""
    result = run_watchdog(db)
    db.commit()
    return WatchdogRunOut(**result)
