"""Response shapes sent to the frontend."""

from datetime import date, datetime
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
    held: int  # reserved for referred patients on their way
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
    address: str | None = None
    pincode: str | None = None
    source: str | None = None
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
    address: str | None = Field(None, max_length=300)
    pincode: str | None = Field(None, pattern=r"^\d{6}$")
    source: str | None = Field(None, max_length=200)
    services: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=40)
    wards: list[WardCountsIn] = Field(default_factory=list, max_length=10)


class FacilityUpdateIn(BaseModel):
    phone: str | None = Field(None, max_length=20)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    has_ambulance: bool | None = None
    address: str | None = Field(None, max_length=300)
    pincode: str | None = Field(None, pattern=r"^\d{6}$")
    source: str | None = Field(None, max_length=200)
    add_services: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=40)


class RecommendationOut(BaseModel):
    facility_id: str
    facility_name: str
    facility_type: str
    phone: str | None
    service: str
    service_availability: str  # AVAILABLE | UNAVAILABLE | UNKNOWN
    ward: str | None  # None when the service needs no bed
    beds_free: int | None  # None when the hospital has not reported that ward
    beds_total: int | None
    beds_updated_at: datetime | None
    beds_stale: bool
    distance_km: float | None
    rejection_rate: float | None
    average_hours_to_accept: float | None
    has_ambulance: bool
    score: float
    reasons: list[str]  # plain-language explanation of the ranking


class HealthOut(BaseModel):
    status: str
    database: str
    version: str
    sms: str = "off"  # on | off | log-only (codes only in the server log)
    email: str = "off"


# ---------- Auth ----------

EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"

# Spaces around the address and capital letters are ignored.
Email = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    Field(max_length=254, pattern=EMAIL_PATTERN),
]


Phone = Annotated[str, BeforeValidator(lambda v: v.strip().replace(" ", "") if isinstance(v, str) else v),
                  Field(pattern=r"^[6-9]\d{9}$", description="10-digit Indian mobile number")]


class OtpRequestIn(BaseModel):
    # Email, or a mobile number when the SMS service is set up.
    email: Email | None = None
    phone: Phone | None = None


class OtpRequestOut(BaseModel):
    message: str
    # Only in development, so the frontend demo can show the code. Never in production.
    dev_code: str | None = None


class OtpVerifyIn(BaseModel):
    email: Email | None = None
    phone: Phone | None = None
    code: str = Field(pattern=r"^\d{6}$")


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=2000)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str | None
    phone: str | None = None
    name: str
    role: str
    facility_id: str | None
    district: str
    photo_id: str | None = None
    # False until the coordinator approves a self sign-up; such a user sees no records yet.
    approved: bool = True


class TokensOut(BaseModel):
    """Either the login tokens, or (code_required) the second step: type your personal code."""

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None  # seconds until the access token expires
    user: UserOut | None = None
    # Second step: the person is approved, so their personal code is needed too.
    code_required: bool = False
    code_token: str | None = None  # short-lived; send it back with the code
    # A newly issued personal code, shown once on the person's own dashboard.
    new_code: str | None = None


class CodeLoginIn(BaseModel):
    code_token: str = Field(max_length=2000)
    code: str = Field(min_length=4, max_length=20)


class MeOut(UserOut):
    # Only ever sent to the person themselves, until they confirm they have written it down.
    new_code: str | None = None


# ---------- Patients and encounters ----------

Language = Literal["en", "bn", "hi", "gu", "mr", "ta", "te", "kn", "ml", "or", "pa", "as", "ur"]


class PatientIn(BaseModel):
    name: Annotated[str, BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
                    Field(min_length=1, max_length=120)]
    age: int = Field(ge=0, le=120)
    sex: Literal["F", "M", "O"] | None = None
    phone: Phone
    abha_number: str | None = Field(None, max_length=20)
    consent_given: bool = Field(description="The ASHA confirms the patient agreed to their data being recorded.")
    email: Email | None = None
    language: Language = "bn"
    address: str | None = Field(None, max_length=300)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)


class PatientUpdateIn(BaseModel):
    """Only the fields sent are changed."""

    name: str | None = Field(None, min_length=1, max_length=120)
    age: int | None = Field(None, ge=0, le=120)
    sex: Literal["F", "M", "O"] | None = None
    phone: Phone | None = None
    email: Email | None = None
    language: Language | None = None
    address: str | None = Field(None, max_length=300)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    reminders: bool | None = None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    age: int
    sex: str | None
    phone: str
    abha_number: str | None
    created_at: datetime
    health_id: str | None = None
    email: str | None = None
    language: str = "bn"
    address: str | None = None
    photo_id: str | None = None
    reminders: bool = True
    deceased_at: datetime | None = None
    death_cause: str | None = None


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
    triage: Literal["EMERGENCY", "PRIORITY", "ROUTINE"] = "ROUTINE"
    vitals: Vitals = Vitals()
    medicines: list[MedicineIn] = Field(default_factory=list, max_length=30)
    # REFERRAL (readings before a referral), HOME_VISIT (routine visit, e.g. "all OK"),
    # VITALS_UPDATE (new readings, e.g. after the checkup).
    kind: Literal["REFERRAL", "HOME_VISIT", "VITALS_UPDATE"] = "REFERRAL"
    referral_id: str | None = None  # the referral these readings update


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
    kind: str = "REFERRAL"
    referral_id: str | None = None
    # LOW / NORMAL / HIGH for each reading that has a normal range.
    flags: dict[str, str] = Field(default_factory=dict)
    recorded_by_role: str | None = None


class VitalRangeOut(BaseModel):
    field: str
    low: float
    high: float
    label: str


# ---------- Referrals ----------


class ReferralIn(BaseModel):
    patient_id: str
    encounter_id: str
    destination_facility_id: str
    requested_service: str = Field(min_length=1, max_length=80)
    # Send the referral even though the hospital reports no free bed (e.g. it is the only option).
    allow_without_bed: bool = False


class RerouteIn(BaseModel):
    destination_facility_id: str
    # Defaults to the service requested in the original referral.
    requested_service: str | None = Field(None, min_length=1, max_length=80)
    note: str | None = Field(None, max_length=300)
    allow_without_bed: bool = False


class AmbulanceRequestIn(BaseModel):
    pickup_note: str = Field(min_length=3, max_length=300, description="Village, landmark, how to find the house")


class AmbulanceDispatchIn(BaseModel):
    eta_minutes: int = Field(ge=1, le=600)
    vehicle_number: str | None = Field(None, max_length=20)
    driver_phone: Phone | None = None


class AmbulanceCancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


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
    sent_at: datetime | None = None  # when the ASHA sent the patient for the checkup


class FacilityBrief(BaseModel):
    id: str
    name: str
    phone: str | None


class BedHoldOut(BaseModel):
    ward: str
    status: str  # HELD | OCCUPIED | RELEASED | EXPIRED
    held_until: datetime
    release_reason: str | None


class AmbulanceOut(BaseModel):
    status: str  # REQUESTED | DISPATCHED | PICKED_UP | COMPLETED | CANCELLED
    pickup_note: str
    requested_at: datetime
    dispatched_at: datetime | None
    eta_minutes: int | None
    expected_at: datetime | None
    vehicle_number: str | None
    driver_phone: str | None
    picked_up_at: datetime | None
    cancel_reason: str | None


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
    bed: BedHoldOut | None = None  # None when no bed was held (service needs none, or no bed data)
    ambulance: AmbulanceOut | None = None  # the latest ambulance trip, if any
    # Re-routing: where this referral came from, and where it was sent on to.
    rerouted_from_code: str | None = None
    rerouted_to_id: str | None = None
    rerouted_to_code: str | None = None
    # ASHA, or PATIENT_EMERGENCY (booked by the patient; the system acted for the ASHA).
    origin: str = "ASHA"
    # Readings at referral time are in `vitals`; the newest readings (e.g. after the
    # checkup) are here, with LOW / NORMAL / HIGH flags.
    latest_vitals: Vitals | None = None
    latest_vitals_at: datetime | None = None
    vitals_flags: dict[str, str] = Field(default_factory=dict)


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


class PublicStep(BaseModel):
    status: str
    at: datetime


class PublicAmbulance(BaseModel):
    status: str
    expected_at: datetime | None
    vehicle_number: str | None
    driver_phone: str | None


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
    sent_at: datetime | None = None


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
    bed_holds_expired: int = 0
    ambulance_alerts: int = 0
    courses_completed: int = 0
    dose_reminders: int = 0
    bed_update_reminders: int = 0


# ---------- Health record ----------


class DeceasedIn(BaseModel):
    cause: str = Field(min_length=2, max_length=300)
    died_at: datetime  # time of death


class PhotoIn(BaseModel):
    # "data:image/jpeg;base64,..." from the phone camera or gallery, resized on the phone.
    data_url: str = Field(min_length=30, max_length=900_000)
    owner_type: Literal["patient", "prescription", "user"]
    owner_id: str | None = None  # patient / prescription id; empty for the user's own photo


class PhotoOut(BaseModel):
    id: str


class ConditionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    status: Literal["ACTIVE", "CHRONIC", "RESOLVED"] = "ACTIVE"
    noted_on: date | None = None
    note: str | None = Field(None, max_length=300)


class ConditionUpdateIn(BaseModel):
    status: Literal["ACTIVE", "CHRONIC", "RESOLVED"]
    note: str | None = Field(None, max_length=300)


class ConditionEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    note: str | None
    at: datetime


class ConditionOut(BaseModel):
    id: str
    name: str
    status: str
    noted_on: date | None
    updated_at: datetime
    history: list[ConditionEventOut]


Timing = Literal["MORNING", "NOON", "EVENING", "NIGHT"]


class CareItemIn(BaseModel):
    """Only the name is required; fill what the prescription or advice gives."""

    kind: Literal["MEDICINE", "PRACTICE"] = "MEDICINE"
    category: Literal["GENERAL", "PREGNANCY", "AFTER_SURGERY", "CHRONIC", "CHILD", "OTHER"] = "GENERAL"
    name: str = Field(min_length=1, max_length=160)
    dose: str | None = Field(None, max_length=60)
    quantity: str | None = Field(None, max_length=60)
    timings: list[Timing] = Field(default_factory=list, max_length=4)
    food: Literal["BEFORE", "AFTER", "WITH", "ANY"] = "ANY"
    start_date: date | None = None  # default today
    duration_days: int | None = Field(None, ge=1, le=3650)  # empty = until stopped
    instructions: str | None = Field(None, max_length=300)


class CareItemOut(BaseModel):
    id: str
    kind: str
    category: str
    name: str
    dose: str | None
    quantity: str | None
    timings: list[str]
    food: str
    start_date: date
    end_date: date | None  # last day of the course
    duration_days: int | None
    days_left: int | None
    instructions: str | None
    status: str
    ended_at: datetime | None
    end_reason: str | None
    prescription_id: str | None


class CareEndIn(BaseModel):
    status: Literal["COMPLETED", "STOPPED"] = "COMPLETED"
    reason: str | None = Field(None, max_length=200)


class PrescriptionIn(BaseModel):
    doctor_name: str | None = Field(None, max_length=120)
    facility_name: str | None = Field(None, max_length=200)
    prescribed_on: date | None = None
    diagnosis: str | None = Field(None, max_length=300)
    notes: str | None = Field(None, max_length=3000)
    referral_id: str | None = None
    # Medicines and advice from the prescription go straight onto the care chart.
    items: list[CareItemIn] = Field(default_factory=list, max_length=30)


class PrescriptionOut(BaseModel):
    id: str
    doctor_name: str | None
    facility_name: str | None
    prescribed_on: date | None
    diagnosis: str | None
    notes: str | None
    photo_id: str | None
    referral_id: str | None
    recorded_by_role: str | None
    created_at: datetime
    items: list[CareItemOut]


class ReferralBrief(BaseModel):
    id: str
    code: str
    status: str
    triage: str
    facility_name: str
    requested_service: str
    reason: str
    origin: str
    created_at: datetime


class PatientRecordOut(BaseModel):
    """Everything about one patient, newest first: for the ASHA, the hospital and the patient."""

    patient: PatientOut
    asha_name: str | None
    conditions: list[ConditionOut]
    prescriptions: list[PrescriptionOut]
    care_chart: list[CareItemOut]  # active items
    finished_care: list[CareItemOut]  # recently completed / stopped
    vitals_history: list[EncounterOut]
    referrals: list[ReferralBrief]
    vital_ranges: list[VitalRangeOut]


class RegisterRowOut(BaseModel):
    """One line of the ASHA's patient register."""

    patient: PatientOut
    last_visit_at: datetime | None
    open_referral_code: str | None
    open_referral_status: str | None
    referrals_count: int
    active_medicines: int


# ---------- Patient sign-in and night emergency ----------


class PatientCodeRequestIn(BaseModel):
    """The mobile number (10 digits) or email the ASHA registered for the patient."""

    phone: Phone | None = None
    email: Email | None = None


class PatientCodeRequestOut(BaseModel):
    # sms | email: a code was sent there (if anyone is registered on it).
    # asha: no SMS service here — ask the ASHA to show a sign-in code.
    channel: str
    dev_code: str | None = None


class PatientCodeVerifyIn(PatientCodeRequestIn):
    code: str = Field(pattern=r"^\d{6}$")


class PatientChooseIn(BaseModel):
    choose_token: str
    patient_id: str


class PatientSignInCodeOut(BaseModel):
    """Shown on the ASHA's phone for the patient to type on theirs."""

    code: str
    phone: str
    expires_at: datetime


class PatientTokenOut(BaseModel):
    token: str
    patient_id: str
    name: str
    health_id: str | None
    language: str


class PatientChoice(BaseModel):
    id: str
    name: str
    age: int
    sex: str | None = None


class PatientChoiceOut(BaseModel):
    """Either signed in, or (a family sharing one phone) the people to choose from."""

    signed_in: PatientTokenOut | None = None
    choose_token: str | None = None
    people: list[PatientChoice] = []


class MyReferralOut(BaseModel):
    """One of the patient's own referrals, as the patient sees it."""

    id: str
    code: str
    status: str
    is_open: bool
    facility_name: str
    facility_phone: str | None
    requested_service: str
    reason: str
    triage: str
    created_at: datetime
    timeline: list[PublicStep]
    rerouted_to_facility: str | None = None
    follow_up_due: datetime | None = None
    ambulance: "PublicAmbulance | None" = None


class EmergencyIn(BaseModel):
    condition: Literal["LABOUR", "PREGNANCY_BLEEDING", "BREATHING", "CHEST_PAIN", "UNCONSCIOUS", "ACCIDENT",
                       "CHILD_HIGH_FEVER", "SNAKE_BITE", "OTHER"]
    note: str | None = Field(None, max_length=300)
    # Where the patient is now (from the phone), for the nearest hospital.
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    pickup_note: str | None = Field(None, max_length=300)


class EmergencyOut(BaseModel):
    referral_code: str
    hospital_name: str
    hospital_phone: str | None
    hospital_address: str | None
    service: str
    bed_held: bool
    ambulance_requested: bool  # the hospital's own ambulance was asked to come
    call: str = "108"
    precautions: list[str]
    reasons: list[str]  # why this hospital
    already_open: bool = False  # an emergency was already booked; this is that one
