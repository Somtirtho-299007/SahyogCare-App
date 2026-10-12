"""Business rules in one place.

Everything a reviewer may want to change lives here: the referral state
machine, who may move a referral, vital-sign ranges, watchdog timings and
rejection reasons.

PLACEHOLDER VALUES: vital ranges, the SpO2 suggestion threshold and all
watchdog timings were chosen by the team, not by clinicians. They must be
reviewed by a doctor or public-health professional before any real use.
"""

import secrets
from datetime import timedelta
from enum import StrEnum


class Role(StrEnum):
    WORKER = "WORKER"  # ASHA / ANM
    FACILITY_STAFF = "FACILITY_STAFF"
    DOCTOR = "DOCTOR"
    COORDINATOR = "COORDINATOR"


class Triage(StrEnum):
    EMERGENCY = "EMERGENCY"
    PRIORITY = "PRIORITY"
    ROUTINE = "ROUTINE"


class Status(StrEnum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ARRIVAL_RECORDED = "ARRIVAL_RECORDED"
    CONSULTED = "CONSULTED"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


# "SYSTEM" is the server itself (scheduled jobs, automatic steps).
SYSTEM = "SYSTEM"

# (from, to) -> who may make that move.
TRANSITIONS: dict[tuple[Status, Status], frozenset[str]] = {
    (Status.CREATED, Status.ACCEPTED): frozenset({Role.FACILITY_STAFF}),
    (Status.CREATED, Status.REJECTED): frozenset({Role.FACILITY_STAFF}),
    (Status.ACCEPTED, Status.ARRIVAL_RECORDED): frozenset({Role.FACILITY_STAFF}),
    (Status.ARRIVAL_RECORDED, Status.CONSULTED): frozenset({Role.DOCTOR}),
    (Status.CONSULTED, Status.OUTCOME_RECORDED): frozenset({Role.DOCTOR}),
    (Status.OUTCOME_RECORDED, Status.FOLLOW_UP_DUE): frozenset({SYSTEM}),
    (Status.FOLLOW_UP_DUE, Status.CLOSED): frozenset(
        {Role.WORKER, Role.DOCTOR, Role.FACILITY_STAFF, Role.COORDINATOR}
    ),
    (Status.FOLLOW_UP_DUE, Status.OVERDUE): frozenset({SYSTEM}),
    (Status.OVERDUE, Status.ESCALATED): frozenset({Role.COORDINATOR}),
    (Status.ESCALATED, Status.CLOSED): frozenset({Role.COORDINATOR}),
}

# The one definition of "open" used by every count and queue.
FINISHED_STATUSES = frozenset({Status.CLOSED, Status.REJECTED})


def is_open(status: str) -> bool:
    return status not in FINISHED_STATUSES


class TransitionError(Exception):
    """Raised when a status change is not allowed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def check_transition(actor: str, current: str, target: str) -> None:
    """Raise TransitionError unless `actor` may move a referral from `current` to `target`."""
    allowed = TRANSITIONS.get((Status(current), Status(target)))
    if allowed is None:
        raise TransitionError(
            "INVALID_STATE_TRANSITION", f"A referral cannot move from {current} to {target}."
        )
    if actor not in allowed:
        raise TransitionError("FORBIDDEN", f"{actor} cannot move a referral from {current} to {target}.")


# ---------- Vital signs (placeholder ranges: outside them is treated as a typing error) ----------

VITAL_RANGES: dict[str, tuple[float, float]] = {
    "systolic": (50, 260),
    "diastolic": (30, 160),
    "pulse": (20, 250),
    "temperature_c": (30, 45),
    "spo2": (50, 100),
    "respiratory_rate": (4, 80),
    "glucose_mg_dl": (20, 800),
    "weight_kg": (0.5, 300),
}


def validate_vitals(vitals: dict[str, float | None]) -> dict[str, str]:
    """Return {field: problem} for values outside plausible ranges. Missing values are fine."""
    problems: dict[str, str] = {}
    for field, value in vitals.items():
        if value is None:
            continue
        if field not in VITAL_RANGES:
            problems[field] = "Unknown vital sign."
            continue
        low, high = VITAL_RANGES[field]
        if not low <= value <= high:
            problems[field] = f"Must be between {low:g} and {high:g}."
    sys_bp, dia_bp = vitals.get("systolic"), vitals.get("diastolic")
    if sys_bp is not None and dia_bp is not None and dia_bp >= sys_bp:
        problems["diastolic"] = "Must be lower than systolic."
    return problems


SPO2_SUGGEST_EMERGENCY_BELOW = 90


def triage_suggestion(vitals: dict[str, float | None]) -> str | None:
    """A hint for the ASHA only. The ASHA always makes the triage decision."""
    spo2 = vitals.get("spo2")
    if spo2 is not None and spo2 < SPO2_SUGGEST_EMERGENCY_BELOW:
        return "Oxygen saturation is low. Consider marking this referral as Emergency."
    return None


# ---------- Referral codes ----------

# No 0/O or 1/I, so codes are easy to read aloud and type.
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 6


def new_referral_code() -> str:
    return "SC-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


# ---------- Watchdog timings (placeholders) ----------

NOT_ACCEPTED_AFTER: dict[Triage, timedelta] = {
    Triage.EMERGENCY: timedelta(hours=1),
    Triage.PRIORITY: timedelta(hours=6),
    Triage.ROUTINE: timedelta(hours=48),
}
NOT_ARRIVED_AFTER: dict[Triage, timedelta] = {
    Triage.EMERGENCY: timedelta(hours=6),
    Triage.PRIORITY: timedelta(hours=24),
    Triage.ROUTINE: timedelta(hours=72),
}
# The Coordinator is alerted when a referral stays silent this many times the threshold.
COORDINATOR_ESCALATION_FACTOR = 2

# Service availability older than this is shown as stale.
AVAILABILITY_STALE_AFTER = timedelta(hours=24)


# ---------- Rejection reasons (fixed list; some teach the system about availability) ----------


class RejectionReason(StrEnum):
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    NO_DOCTOR_AVAILABLE = "NO_DOCTOR_AVAILABLE"
    NO_BEDS = "NO_BEDS"
    NEEDS_HIGHER_FACILITY = "NEEDS_HIGHER_FACILITY"
    INCOMPLETE_INFORMATION = "INCOMPLETE_INFORMATION"
    OTHER = "OTHER"


REJECTION_LABELS: dict[RejectionReason, str] = {
    RejectionReason.SERVICE_UNAVAILABLE: "Requested service not available",
    RejectionReason.NO_DOCTOR_AVAILABLE: "No doctor available",
    RejectionReason.NO_BEDS: "No beds available",
    RejectionReason.NEEDS_HIGHER_FACILITY: "Patient needs a higher facility",
    RejectionReason.INCOMPLETE_INFORMATION: "Referral information incomplete",
    RejectionReason.OTHER: "Other (note required)",
}

# Rejections for these reasons mark the requested service unavailable at that facility.
MARKS_SERVICE_UNAVAILABLE = frozenset(
    {RejectionReason.SERVICE_UNAVAILABLE, RejectionReason.NO_DOCTOR_AVAILABLE}
)


# ---------- Login (one-time codes) ----------

OTP_LENGTH = 6
OTP_VALID_FOR = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_AFTER = timedelta(seconds=60)
