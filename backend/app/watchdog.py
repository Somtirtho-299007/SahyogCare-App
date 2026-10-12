"""Referral watchdog: treats *nothing happening* as a warning sign.

See docs/WORKFLOW.md, "Time rules (watchdog)". Runs every few minutes in the
background (see app/main.py) and can be started by hand with
POST /api/v1/watchdog/run. Alerts are deduplicated, so running it often is safe.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Facility, FollowUp, Patient, Referral, User
from app.rules import (
    COORDINATOR_ESCALATION_FACTOR,
    NOT_ACCEPTED_AFTER,
    NOT_ARRIVED_AFTER,
    WATCHDOG_EVERY,
    Role,
    Status,
    Triage,
)
from app.timeutil import as_utc, utcnow
from app.workflow import move, notify

log = logging.getLogger("sahyogcare.watchdog")


def _hours(delta) -> int:
    return int(delta.total_seconds() // 3600)


def _coordinators(db: Session, referral: Referral) -> list[str]:
    creator = db.get(User, referral.created_by_id)
    return list(
        db.scalars(
            select(User.id).where(
                User.role == Role.COORDINATOR, User.district == creator.district, User.is_active.is_(True)
            )
        )
    )


def _last_event_at(referral: Referral, status: Status) -> datetime | None:
    times = [as_utc(e.at) for e in referral.events if e.to_status == status]
    return max(times) if times else None


def run_watchdog(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Check every open referral once. Returns how many alerts or changes were made."""
    now = now or utcnow()
    counts = {"not_accepted": 0, "not_arrived": 0, "follow_ups_overdue": 0, "coordinator_alerts": 0}

    watched = db.scalars(
        select(Referral).where(Referral.status.in_([Status.CREATED, Status.ACCEPTED, Status.FOLLOW_UP_DUE]))
    )
    for referral in watched:
        patient = db.get(Patient, referral.patient_id)
        facility = db.get(Facility, referral.destination_facility_id)
        phone = f" Call the facility: {facility.phone}." if facility.phone else " Please call the facility."
        triage = Triage(referral.triage)

        if referral.status == Status.CREATED:
            waited = now - as_utc(referral.created_at)
            limit = NOT_ACCEPTED_AFTER[triage]
            if waited > limit:
                msg = (f"{referral.code}: {facility.name} has not accepted {patient.name} yet "
                       f"({_hours(waited)} h).{phone}")
                if notify(db, referral.created_by_id, referral, "WATCH_NOT_ACCEPTED", msg):
                    counts["not_accepted"] += 1
            if waited > limit * COORDINATOR_ESCALATION_FACTOR:
                for cid in _coordinators(db, referral):
                    if notify(db, cid, referral, "WATCH_NOT_ACCEPTED",
                              f"{referral.code} ({triage.lower()}) has waited {_hours(waited)} h "
                              f"for {facility.name} to accept."):
                        counts["coordinator_alerts"] += 1

        elif referral.status == Status.ACCEPTED:
            accepted_at = _last_event_at(referral, Status.ACCEPTED) or as_utc(referral.updated_at)
            waited = now - accepted_at
            limit = NOT_ARRIVED_AFTER[triage]
            if waited > limit:
                msg = (f"{referral.code}: {patient.name} has not arrived at {facility.name} yet "
                       f"({_hours(waited)} h since acceptance). Please check on the patient.")
                if notify(db, referral.created_by_id, referral, "WATCH_NOT_ARRIVED", msg):
                    counts["not_arrived"] += 1
            if waited > limit * COORDINATOR_ESCALATION_FACTOR:
                for cid in _coordinators(db, referral):
                    if notify(db, cid, referral, "WATCH_NOT_ARRIVED",
                              f"{referral.code}: patient has not reached {facility.name} "
                              f"{_hours(waited)} h after acceptance."):
                        counts["coordinator_alerts"] += 1

        else:  # FOLLOW_UP_DUE
            due = db.scalar(select(FollowUp).where(FollowUp.referral_id == referral.id, FollowUp.status == "DUE"))
            if due is not None and as_utc(due.due_at) < now:
                move(db, referral, Status.OVERDUE, None, note="Follow-up due date passed")
                due.status = "OVERDUE"
                counts["follow_ups_overdue"] += 1
                for cid in _coordinators(db, referral):
                    if notify(db, cid, referral, "WATCH_FOLLOW_UP_OVERDUE",
                              f"{referral.code}: follow-up for {patient.name} is overdue."):
                        counts["coordinator_alerts"] += 1
    return counts


async def watchdog_loop(session_factory) -> None:
    """Background task started with the app."""
    while True:
        await asyncio.sleep(WATCHDOG_EVERY.total_seconds())
        try:
            def _run():
                with session_factory() as db:
                    result = run_watchdog(db)
                    db.commit()
                    return result

            result = await asyncio.to_thread(_run)
            if any(result.values()):
                log.info("watchdog: %s", result)
        except Exception:  # never let the loop die
            log.exception("watchdog run failed")
