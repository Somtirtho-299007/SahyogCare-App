"""Response shapes sent to the frontend."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service: str
    availability: str  # AVAILABLE | UNAVAILABLE | UNKNOWN
    availability_note: str | None
    availability_updated_at: datetime | None
    stale: bool  # True when the availability information is older than the stale limit


class WardOut(BaseModel):
    ward: str  # GENERAL | EMERGENCY | MATERNITY | PAEDIATRIC | ICU
    total: int
    occupied: int
    free: int
    updated_at: datetime
    stale: bool  # True when the counts have not been confirmed recently


class FacilityOut(BaseModel):
    id: str
    name: str
    type: str
    district: str
    phone: str | None
    beds: int | None
    latitude: float | None = None
    longitude: float | None = None
    has_ambulance: bool = False
    services: list[ServiceOut]
    wards: list[WardOut] = Field(default_factory=list)


Ward = Literal["GENERAL", "EMERGENCY", "MATERNITY", "PAEDIATRIC", "ICU"]


class WardIn(BaseModel):
    total: int = Field(ge=0, le=5000)
    occupied: int = Field(ge=0, le=5000)


class WardCountsIn(WardIn):
    ward: Ward


class FacilityIn(BaseModel):
    """A hospital added by the coordinator (e.g. from the National Hospital Directory)."""

    name: str = Field(min_length=2, max_length=200)
    type: str = Field(min_length=2, max_length=80)
    phone: str | None = Field(None, max_length=20)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    has_ambulance: bool = False
    hfr_id: str | None = Field(None, max_length=40)
    services: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=40)
    wards: list[WardCountsIn] = Field(default_factory=list, max_length=10)


class FacilityUpdateIn(BaseModel):
    phone: str | None = Field(None, max_length=20)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    has_ambulance: bool | None = None
    add_services: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=40)


class HealthOut(BaseModel):
    status: str
    database: str
    version: str


# ---------- Auth ----------

EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"

# Spaces around the address and capital letters are ignored.
Email = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    Field(max_length=254, pattern=EMAIL_PATTERN),
]


class OtpRequestIn(BaseModel):
    email: Email


class OtpRequestOut(BaseModel):
    message: str
    # Only in development, so the frontend demo can show the code. Never in production.
    dev_code: str | None = None


class OtpVerifyIn(BaseModel):
    email: Email
    code: str = Field(pattern=r"^\d{6}$")


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=2000)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    role: str
    facility_id: str | None
    district: str


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires
    user: UserOut


# ---------- Patients and encounters ----------

Phone = Annotated[str, BeforeValidator(lambda v: v.strip().replace(" ", "") if isinstance(v, str) else v),
                  Field(pattern=r"^[6-9]\d{9}$", description="10-digit Indian mobile number")]


class PatientIn(BaseModel):
    name: Annotated[str, BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
                    Field(min_length=1, max_length=120)]
    age: int = Field(ge=0, le=120)
    sex: Literal["F", "M", "O"] | None = None
    phone: Phone
    abha_number: str | None = Field(None, max_length=20)
    consent_given: bool = Field(description="The ASHA confirms the patient agreed to their data being recorded.")


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    age: int
    sex: str | None
    phone: str
    abha_number: str | None
    created_at: datetime


class PatientCreatedOut(PatientOut):
    # Set when this ASHA already has a patient with the same name and phone.
    possible_duplicate_of: str | None = None


class Vitals(BaseModel):
    systolic: float | None = None
    diastolic: float | None = None
    pulse: float | None = None
    temperature_c: float | None = None
    spo2: float | None = None
    respiratory_rate: float | None = None
    glucose_mg_dl: float | None = None
    weight_kg: float | None = None


class MedicineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dose: str | None = Field(None, max_length=60)
    frequency: str | None = Field(None, max_length=60)
    notes: str | None = Field(None, max_length=200)


class MedicineOut(MedicineIn):
    model_config = ConfigDict(from_attributes=True)


class EncounterIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    triage: Literal["EMERGENCY", "PRIORITY", "ROUTINE"]
    vitals: Vitals = Vitals()
    medicines: list[MedicineIn] = Field(default_factory=list, max_length=30)


class EncounterOut(BaseModel):
    id: str
    patient_id: str
    reason: str
    triage: str
    vitals: Vitals
    medicines: list[MedicineOut]
    created_at: datetime
    # A hint for the ASHA only; she makes the triage decision.
    triage_suggestion: str | None = None


# ---------- Referrals ----------


class ReferralIn(BaseModel):
    patient_id: str
    encounter_id: str
    destination_facility_id: str
    requested_service: str = Field(min_length=1, max_length=80)


class RejectIn(BaseModel):
    reason: Literal[
        "SERVICE_UNAVAILABLE", "NO_DOCTOR_AVAILABLE", "NO_BEDS",
        "NEEDS_HIGHER_FACILITY", "INCOMPLETE_INFORMATION", "OTHER",
    ]
    note: str | None = Field(None, max_length=300)


class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=1000)


class OutcomeIn(BaseModel):
    note: str | None = Field(None, max_length=1000)
    follow_up_days: int = Field(7, ge=1, le=365)


class EventOut(BaseModel):
    from_status: str | None
    to_status: str
    at: datetime
    note: str | None
    source: str
    actor_role: str | None  # None = done automatically by the system


class FollowUpOut(BaseModel):
    due_at: datetime
    status: str


class FacilityBrief(BaseModel):
    id: str
    name: str
    phone: str | None


class ReferralOut(BaseModel):
    id: str
    code: str
    status: str
    is_open: bool
    triage: str
    requested_service: str
    reason: str
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime
    patient: PatientOut
    facility: FacilityBrief
    vitals: Vitals
    events: list[EventOut]
    follow_up: FollowUpOut | None


class RejectionReasonOut(BaseModel):
    code: str
    label: str
    marks_service_unavailable: bool


# ---------- Referral pass ----------


class PassOut(BaseModel):
    code: str
    qr_text: str  # put this string in a QR code; the facility scans it


class PassVerifyIn(BaseModel):
    qr_text: str = Field(max_length=1000)
    # When the pass was scanned, if the scan happened offline and is being synced later.
    scanned_at: datetime | None = None


class PassVerifyOut(BaseModel):
    referral: ReferralOut
    already_recorded: bool


# ---------- Public patient lookup ----------


class PublicLookupIn(BaseModel):
    code: Annotated[str, BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
                    Field(pattern=r"^SC-[0-9A-Z]{6}$")]
    phone_last4: str = Field(pattern=r"^\d{4}$")


class PublicStep(BaseModel):
    status: str
    at: datetime


class PublicLookupOut(BaseModel):
    code: str
    status: str
    facility_name: str
    timeline: list[PublicStep]
    checklist: list[str]


# ---------- Notifications ----------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    referral_id: str | None
    kind: str
    message: str
    created_at: datetime
    read_at: datetime | None


# ---------- Follow-ups ----------


class FollowUpItemOut(BaseModel):
    id: str
    referral_id: str
    referral_code: str
    referral_status: str
    patient_name: str
    patient_phone: str
    facility_name: str
    due_at: datetime
    status: str  # DUE | OVERDUE | ESCALATED | COMPLETED
    is_late: bool


# ---------- Insights ----------


class ActivitySummaryOut(BaseModel):
    month: str  # YYYY-MM
    referrals_created: int
    referrals_completed: int
    referrals_rejected: int
    follow_ups_completed: int
    open_now: int
    note: str = "A record of your work for your own use. It is not an official incentive claim."


class FacilityPerformance(BaseModel):
    facility_id: str
    facility_name: str
    referrals_received: int
    accepted: int
    rejected: int
    waiting_for_acceptance: int
    average_hours_to_accept: float | None
    rejection_rate: float | None


class DashboardOut(BaseModel):
    role: str
    open: int
    open_by_triage: dict[str, int]
    awaiting_acceptance: int
    follow_ups_due: int
    overdue: int
    closed_this_month: int
    unread_notifications: int
    # Coordinators only: where referrals get stuck.
    facilities: list[FacilityPerformance] | None = None


class WatchdogRunOut(BaseModel):
    not_accepted: int
    not_arrived: int
    follow_ups_overdue: int
    coordinator_alerts: int
