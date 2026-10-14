"""Referral watchdog: treats *nothing happening* as a warning sign.

See docs/WORKFLOW.md, "Time rules (watchdog)". Every few minutes it also completes
finished medicine courses, sends dose reminders to patients, and reminds hospital
staff at shift change to update bed counts.

How it runs (alerts are deduplicated, so running it often is safe):
- inside the web server, every 5 minutes (default; SAHYOG_WATCHDOG_ENABLED=true);
- or, with several servers, once from outside: `python -m app.watchdog` (e.g. a cron
  job) or POST /api/v1/watchdog/tick with the X-Cron-Secret header. A database lock
  makes sure two copies never run at the same moment.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import ambulance, beds, messaging
from app.models import AmbulanceTrip, BedWard, CareItem, Facility, FollowUp, Patient, Referral, ReminderLog, User
from app.records import complete_finished_courses, end_date
from app.recommend import recommend
from app.rules import (
    AMBULANCE_LATE_AFTER_ETA,
    AMBULANCE_NOT_DISPATCHED_AFTER,
    BED_REMINDER_HOURS,
    BED_REMINDER_STALE,
    BEFORE_FOOD_EARLIER,
    DOSE_SLOTS,
    LOCAL_UTC_OFFSET,
    REMINDER_WINDOW,
    CareKind,
    CareStatus,
    COORDINATOR_ESCALATION_FACTOR,
    NATIONAL_AMBULANCE_NUMBER,
    NOT_ACCEPTED_AFTER,
    NOT_ARRIVED_AFTER,
    WATCHDOG_EVERY,
    AmbulanceStatus,
    HoldStatus,
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
    counts = {"not_accepted": 0, "not_arrived": 0, "follow_ups_overdue": 0, "coordinator_alerts": 0,
              "bed_holds_expired": 0, "ambulance_alerts": 0, "courses_completed": 0, "dose_reminders": 0,
              "bed_update_reminders": 0}
    _expire_bed_holds(db, now, counts)
    _check_ambulances(db, now, counts)
    local = now + LOCAL_UTC_OFFSET
    counts["courses_completed"] = complete_finished_courses(db, today=local.date())
    _dose_reminders(db, now, counts)
    _bed_update_reminders(db, now, counts)

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


def _best_other(db: Session, referral: Referral) -> str:
    owner = db.get(User, referral.created_by_id)
    best = recommend(db, referral.requested_service, district=owner.district,
                     exclude={referral.destination_facility_id}, limit=1)
    if not best or (best[0].beds_free is not None and best[0].beds_free <= 0):
        return ""
    b = best[0]
    beds_txt = f" ({b.beds_free} bed{'s' if b.beds_free != 1 else ''} free)" if b.beds_free else ""
    return f" Suggested instead: {b.facility_name}{beds_txt}."


def _expire_bed_holds(db: Session, now: datetime, counts: dict[str, int]) -> None:
    """A bed nobody used in time goes back to the pool, and the ASHA is offered the next best hospital."""
    for hold in beds.expired_holds(db, now):
        referral = db.get(Referral, hold.referral_id)
        hold.status, hold.ended_at = HoldStatus.EXPIRED, now
        hold.release_reason = ("Hospital did not accept in time" if referral.status == Status.CREATED
                               else "Patient did not arrive in time")
        counts["bed_holds_expired"] += 1
        facility = db.get(Facility, referral.destination_facility_id)
        notify(db, referral.created_by_id, referral, "BED_HOLD_EXPIRED",
               f"{referral.code}: the bed held at {facility.name} was released "
               f"({hold.release_reason.lower()}).{_best_other(db, referral)}")
        for cid in _coordinators(db, referral):
            if notify(db, cid, referral, "BED_HOLD_EXPIRED",
                      f"{referral.code} ({referral.triage.lower()}): bed hold at {facility.name} expired — "
                      f"{hold.release_reason.lower()}."):
                counts["coordinator_alerts"] += 1


def _check_ambulances(db: Session, now: datetime, counts: dict[str, int]) -> None:
    trips = db.scalars(select(AmbulanceTrip).where(
        AmbulanceTrip.status.in_([AmbulanceStatus.REQUESTED, AmbulanceStatus.DISPATCHED])
    ))
    for trip in trips:
        referral = db.get(Referral, trip.referral_id)
        facility = db.get(Facility, trip.facility_id)
        triage = Triage(referral.triage)
        if trip.status == AmbulanceStatus.REQUESTED:
            if now - as_utc(trip.requested_at) <= AMBULANCE_NOT_DISPATCHED_AFTER[triage]:
                continue
            kind = "WATCH_AMBULANCE_NOT_SENT"
            msg = (f"{referral.code}: {facility.name} has not sent its ambulance yet. "
                   f"Call {NATIONAL_AMBULANCE_NUMBER} now.")
        else:
            due = ambulance.expected_at(trip)
            if due is None or now - due <= AMBULANCE_LATE_AFTER_ETA:
                continue
            kind = "WATCH_AMBULANCE_LATE"
            msg = (f"{referral.code}: the ambulance from {facility.name} is over "
                   f"{int(AMBULANCE_LATE_AFTER_ETA.total_seconds() // 60)} min late."
                   + (f" Driver: {trip.driver_phone}." if trip.driver_phone else "")
                   + f" If it is not coming, call {NATIONAL_AMBULANCE_NUMBER}.")
        if notify(db, referral.created_by_id, referral, kind, msg):
            counts["ambulance_alerts"] += 1
        for cid in _coordinators(db, referral):
            if notify(db, cid, referral, kind, msg):
                counts["coordinator_alerts"] += 1


# ---------- Medicine reminders ----------


def _slot_start(local_day, slot: str) -> datetime:
    hour, minute = DOSE_SLOTS[slot]
    return datetime(local_day.year, local_day.month, local_day.day, hour, minute)


def _dose_reminders(db: Session, now: datetime, counts: dict[str, int]) -> None:
    """At each dose time, one message per patient listing what to take, in their language."""
    local = (now + LOCAL_UTC_OFFSET).replace(tzinfo=None)
    today = local.date()
    items = db.scalars(select(CareItem).where(CareItem.status == CareStatus.ACTIVE,
                                              CareItem.kind == CareKind.MEDICINE,
                                              CareItem.start_date <= today))
    due: dict[tuple[str, str], list[CareItem]] = {}
    for item in items:
        last = end_date(item)
        if last is not None and last < today:
            continue
        for slot in item.timings or []:
            if slot in DOSE_SLOTS:
                due.setdefault((item.patient_id, slot), []).append(item)
    for (patient_id, slot), slot_items in due.items():
        # Before-food doses are reminded a little earlier; one message covers the whole slot.
        start = _slot_start(today, slot) - (BEFORE_FOOD_EARLIER if any(i.food == "BEFORE" for i in slot_items)
                                            else timedelta(0))
        if not start <= local < start + REMINDER_WINDOW:
            continue
        patient = db.get(Patient, patient_id)
        if patient.deceased_at is not None or not patient.reminders:
            continue
        if db.scalar(select(ReminderLog.id).where(ReminderLog.patient_id == patient_id, ReminderLog.day == today,
                                                  ReminderLog.slot == slot)):
            continue
        lang = patient.language if patient.language in messaging.SLOT_NAMES else "en"
        parts = []
        for i in slot_items:
            extra = ", ".join(x for x in (i.dose, messaging.FOOD_WORDS[lang].get(i.food)) if x)
            parts.append(f"{i.name} ({extra})" if extra else i.name)
        channel = messaging.send(
            phone=patient.phone, email=patient.email, subject="SahyogCare: medicine time",
            text=messaging.text("dose", lang, name=patient.name, slot=messaging.SLOT_NAMES[lang][slot],
                                items="; ".join(parts)))
        db.add(ReminderLog(patient_id=patient_id, day=today, slot=slot, channel=channel))
        counts["dose_reminders"] += 1


# ---------- Bed counts at shift change ----------


def _bed_update_reminders(db: Session, now: datetime, counts: dict[str, int]) -> None:
    local = now + LOCAL_UTC_OFFSET
    if local.hour not in BED_REMINDER_HOURS or local.minute >= REMINDER_WINDOW.total_seconds() // 60:
        return
    kind = f"BED_UPDATE_{local:%Y%m%d}_{local.hour:02d}"
    for facility in db.scalars(select(Facility).where(Facility.active.is_(True))):
        wards = list(db.scalars(select(BedWard).where(BedWard.facility_id == facility.id)))
        old = [w.ward.lower() for w in wards if now - as_utc(w.updated_at) > BED_REMINDER_STALE]
        if not old:
            continue
        msg = (f"Shift change: please update today's bed counts at {facility.name} "
               f"({', '.join(old)}). Fresh counts send you the right patients.")
        for staff in db.scalars(select(User).where(User.facility_id == facility.id, User.role == Role.FACILITY_STAFF,
                                                   User.is_active.is_(True))):
            if notify(db, staff.id, None, kind, msg):
                counts["bed_update_reminders"] += 1


# ---------- Running it ----------

WATCHDOG_LOCK_ID = 727274  # any fixed number; PostgreSQL advisory lock


def run_once(session_factory) -> dict[str, int] | None:
    """One full run in its own transaction. Returns None when another copy is running right now."""
    with session_factory() as db:
        if db.bind.dialect.name == "postgresql":
            if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": WATCHDOG_LOCK_ID}):
                return None
        result = run_watchdog(db)
        db.commit()
        return result


async def watchdog_loop(session_factory) -> None:
    """Background task started with the app."""
    while True:
        await asyncio.sleep(WATCHDOG_EVERY.total_seconds())
        try:
            result = await asyncio.to_thread(run_once, session_factory)
            if result and any(result.values()):
                log.info("watchdog: %s", result)
        except Exception:  # never let the loop die
            log.exception("watchdog run failed")


if __name__ == "__main__":  # python -m app.watchdog  (one run, e.g. from a cron job)
    from app.db import SessionLocal

    logging.basicConfig(level=logging.INFO)
    print(run_once(SessionLocal) or "another run is in progress; skipped")
