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
    # Sent on to another hospital; the new referral carries on from here.
    REROUTED = "REROUTED"


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
    # SYSTEM when the due date passes; the ASHA when she reports the visit was missed.
    (Status.FOLLOW_UP_DUE, Status.OVERDUE): frozenset({SYSTEM, Role.WORKER}),
    # A late follow-up still counts once it happens.
    (Status.OVERDUE, Status.CLOSED): frozenset({Role.WORKER, Role.COORDINATOR}),
    (Status.OVERDUE, Status.ESCALATED): frozenset({Role.COORDINATOR}),
    (Status.ESCALATED, Status.CLOSED): frozenset({Role.COORDINATOR}),
    # Before the patient reaches the hospital, the ASHA or coordinator may send her elsewhere.
    (Status.CREATED, Status.REROUTED): frozenset({Role.WORKER, Role.COORDINATOR}),
    (Status.ACCEPTED, Status.REROUTED): frozenset({Role.WORKER, Role.COORDINATOR}),
}

# The one definition of "open" used by every count and queue.
FINISHED_STATUSES = frozenset({Status.CLOSED, Status.REJECTED, Status.REROUTED})

# A referral in these states can be sent on to another hospital
# (REJECTED: the ASHA picks the next hospital after a refusal).
REROUTABLE_STATUSES = frozenset({Status.CREATED, Status.ACCEPTED, Status.REJECTED})


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
# Login code requests allowed per IP address per minute (anyone may sign up).
OTP_REQUESTS_PER_MINUTE = 10


# ---------- Referrals ----------

DEFAULT_FOLLOW_UP_DAYS = 7
URGENCY_ORDER = {Triage.EMERGENCY: 0, Triage.PRIORITY: 1, Triage.ROUTINE: 2}

# Shown to patients on the public status page.
PATIENT_CHECKLIST = [
    "Carry your referral code or referral pass",
    "Bring your current medicines and any reports",
    "Keep a phone number reachable",
    "Show your referral pass at the facility desk",
]

# Public status lookups allowed per IP address per minute.
PUBLIC_LOOKUPS_PER_MINUTE = 5


# ---------- Watchdog ----------

# How often the background watchdog runs.
WATCHDOG_EVERY = timedelta(minutes=5)


# ---------- Beds (placeholders: to be agreed with the district health office) ----------


class Ward(StrEnum):
    GENERAL = "GENERAL"
    EMERGENCY = "EMERGENCY"
    MATERNITY = "MATERNITY"
    PAEDIATRIC = "PAEDIATRIC"
    ICU = "ICU"


# Which ward a referred patient needs, by requested service.
# Services not listed here (e.g. Diagnostics) need no bed.
SERVICE_WARD: dict[str, Ward] = {
    "general medicine": Ward.GENERAL,
    "emergency": Ward.EMERGENCY,
    "maternity": Ward.MATERNITY,
    "paediatrics": Ward.PAEDIATRIC,
    "pediatrics": Ward.PAEDIATRIC,
    "icu": Ward.ICU,
    "critical care": Ward.ICU,
}


def ward_for_service(service: str) -> Ward | None:
    return SERVICE_WARD.get(service.strip().lower())


class HoldStatus(StrEnum):
    HELD = "HELD"  # reserved for the patient, counted as taken
    OCCUPIED = "OCCUPIED"  # the patient arrived and is in the bed
    RELEASED = "RELEASED"  # given back (rejected, sent elsewhere, cancelled)
    EXPIRED = "EXPIRED"  # nobody acted in time, given back automatically


# How long a bed is held after the referral is created, before the hospital accepts.
HOLD_UNTIL_ACCEPTED: dict[Triage, timedelta] = {
    Triage.EMERGENCY: timedelta(hours=1),
    Triage.PRIORITY: timedelta(hours=6),
    Triage.ROUTINE: timedelta(hours=48),
}
# Once accepted, the bed stays held this long for the patient to arrive.
HOLD_UNTIL_ARRIVED = NOT_ARRIVED_AFTER

# Bed counts older than this are shown as "not confirmed recently" and ranked lower.
BED_DATA_STALE_AFTER = timedelta(hours=12)


# ---------- Hospital recommendation (placeholder weights) ----------

# Higher score = better choice. Every number here is a team placeholder.
SCORE_BEDS_FREE = 50  # the right ward has at least one free bed
SCORE_PER_FREE_BED = 1  # small bonus per free bed, up to SCORE_FREE_BED_CAP beds
SCORE_FREE_BED_CAP = 10
SCORE_NO_BEDS = -60  # the right ward is full
SCORE_STALE_BEDS = -15  # bed counts not confirmed recently
SCORE_SERVICE_UNAVAILABLE = -100  # a recent rejection said the service is not running
SCORE_REJECTION_RATE = -30  # multiplied by the recent rejection rate (0..1)
SCORE_PER_HOUR_TO_ACCEPT = -1  # per average hour taken to accept, up to 24
SCORE_PER_KM = -1  # per kilometre, when both locations are known
# Performance is judged on this many recent days, and only once there are enough referrals.
PERFORMANCE_WINDOW = timedelta(days=30)
PERFORMANCE_MIN_REFERRALS = 3


# ---------- Ambulance ----------


class AmbulanceStatus(StrEnum):
    REQUESTED = "REQUESTED"  # the ASHA asked the hospital for its ambulance
    DISPATCHED = "DISPATCHED"  # the hospital sent it
    PICKED_UP = "PICKED_UP"  # the patient is on board
    COMPLETED = "COMPLETED"  # the patient reached the hospital
    CANCELLED = "CANCELLED"


AMBULANCE_OPEN = frozenset({AmbulanceStatus.REQUESTED, AmbulanceStatus.DISPATCHED, AmbulanceStatus.PICKED_UP})

# National ambulance number, shown whenever a hospital ambulance is not coming quickly.
NATIONAL_AMBULANCE_NUMBER = "108"

# Alert when a requested ambulance has not been sent within this time.
AMBULANCE_NOT_DISPATCHED_AFTER: dict[Triage, timedelta] = {
    Triage.EMERGENCY: timedelta(minutes=15),
    Triage.PRIORITY: timedelta(hours=1),
    Triage.ROUTINE: timedelta(hours=4),
}
# Alert when a sent ambulance is this late beyond its ETA.
AMBULANCE_LATE_AFTER_ETA = timedelta(minutes=30)


# ---------- Invite codes ----------

# Readable prefix by role, then a random part. The prefix only helps people read the
# code; the random part (8 characters from 32, about a trillion combinations) is the secret.
INVITE_PREFIX = {
    Role.COORDINATOR: "DA",
    Role.FACILITY_STAFF: "HS",
    Role.DOCTOR: "DR",
    Role.WORKER: "AS",
}
INVITE_RANDOM_LENGTH = 8
# Wrong codes a logged-in person may try before waiting (stops guessing).
INVITE_ATTEMPTS_PER_10_MIN = 5
# Codes for coordinators are always single-use and short-lived.
COORDINATOR_INVITE_MAX_DAYS = 7


def new_invite_code(role: str, place: str) -> str:
    """e.g. HS-KAL-7K3M9QWX: role, first three letters of the hospital or district, secret part."""
    letters = "".join(ch for ch in place.upper() if ch.isalpha())[:3].ljust(3, "X")
    secret = "".join(secrets.choice(CODE_ALPHABET) for _ in range(INVITE_RANDOM_LENGTH))
    return f"{INVITE_PREFIX[Role(role)]}-{letters}-{secret}"
