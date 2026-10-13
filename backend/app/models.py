"""Database tables. See docs/WORKFLOW.md section 7."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.rules import AmbulanceStatus, HoldStatus, Role, Status, Triage, Ward


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum_check(column: str, values) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{column}_valid")


ID = String(36)


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(80))
    district: Mapped[str] = mapped_column(String(80), index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    beds: Mapped[int | None] = mapped_column(Integer)
    hfr_id: Mapped[str | None] = mapped_column(String(40))  # ABDM Health Facility Registry, later
    # Approximate location, used to rank nearby hospitals first.
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    has_ambulance: Mapped[bool] = mapped_column(Boolean, default=False)
    address: Mapped[str | None] = mapped_column(String(300))
    pincode: Mapped[str | None] = mapped_column(String(6))
    # Where the details came from, e.g. "nadia.gov.in — Hospitals list (accessed Oct 2026)".
    source: Mapped[str | None] = mapped_column(String(200))
    # Hidden hospitals (e.g. demo data in production) are not offered for referrals.
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    services: Mapped[list["FacilityService"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan", order_by="FacilityService.service"
    )
    wards: Mapped[list["BedWard"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan", order_by="BedWard.ward"
    )


class FacilityService(Base):
    """A service a facility lists, with what we last learned about its availability."""

    __tablename__ = "facility_services"
    __table_args__ = (
        UniqueConstraint("facility_id", "service"),
        _enum_check("availability", ["AVAILABLE", "UNAVAILABLE", "UNKNOWN"]),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"))
    service: Mapped[str] = mapped_column(String(80))
    availability: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    availability_note: Mapped[str | None] = mapped_column(String(200))
    availability_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a rejection taught us the service is unavailable.
    learned_from_referral_id: Mapped[str | None] = mapped_column(ID)

    facility: Mapped[Facility] = relationship(back_populates="services")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (_enum_check("role", list(Role)),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    facility_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"))
    district: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # False for people who signed up themselves and are waiting for the coordinator
    # to approve their role. They can log in but see no records until approved.
    approved: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint("age >= 0 AND age <= 120", name="ck_age_range"),
        _enum_check("sex", ["F", "M", "O"]),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(1))
    phone: Mapped[str] = mapped_column(String(10), index=True)
    abha_number: Mapped[str | None] = mapped_column(String(20))  # ABDM, later
    consent_recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Encounter(Base):
    """One visit. Readings are never overwritten; a new visit is a new encounter."""

    __tablename__ = "encounters"
    __table_args__ = (_enum_check("triage", list(Triage)),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    triage: Mapped[str] = mapped_column(String(20))
    systolic: Mapped[float | None] = mapped_column(Float)
    diastolic: Mapped[float | None] = mapped_column(Float)
    pulse: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    spo2: Mapped[float | None] = mapped_column(Float)
    respiratory_rate: Mapped[float | None] = mapped_column(Float)
    glucose_mg_dl: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    medicines: Mapped[list["Medicine"]] = relationship(cascade="all, delete-orphan")


class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    dose: Mapped[str | None] = mapped_column(String(60))
    frequency: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(String(200))


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (
        _enum_check("status", list(Status)),
        _enum_check("triage", list(Triage)),
        CheckConstraint("follow_up_days IS NULL OR follow_up_days BETWEEN 1 AND 365", name="ck_follow_up_days"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"))
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    destination_facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    requested_service: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    triage: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=Status.CREATED, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(40))
    follow_up_days: Mapped[int | None] = mapped_column(Integer)
    # Set when this referral continues an earlier one that was sent on from another hospital.
    rerouted_from_id: Mapped[str | None] = mapped_column(ForeignKey("referrals.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    events: Mapped[list["ReferralEvent"]] = relationship(
        back_populates="referral", order_by="ReferralEvent.at", cascade="all, delete-orphan"
    )


class ReferralEvent(Base):
    """Append-only history of every status change."""

    __tablename__ = "referral_events"
    __table_args__ = (_enum_check("source", ["ONLINE", "OFFLINE_PASS", "SYSTEM"]),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))  # None = system
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="ONLINE")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    referral: Mapped[Referral] = relationship(back_populates="events")


class FollowUp(Base):
    __tablename__ = "follow_ups"
    __table_args__ = (_enum_check("status", ["DUE", "COMPLETED", "MISSED", "OVERDUE", "ESCALATED"]),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    assigned_to_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="DUE")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the ASHA told the patient to go for the follow-up checkup.
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    # One watchdog alert per referral per kind, however often the job runs.
    __table_args__ = (UniqueConstraint("user_id", "referral_id", "kind"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    referral_id: Mapped[str | None] = mapped_column(ForeignKey("referrals.id"))
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Who did what to which record. IDs only — never names or phone numbers."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(ID)
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(ID)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class BedWard(Base):
    """Bed counts for one ward of one hospital, kept up to date by its staff (or the coordinator).

    Free beds = total - occupied - beds held for incoming referrals.
    """

    __tablename__ = "bed_wards"
    __table_args__ = (
        UniqueConstraint("facility_id", "ward"),
        _enum_check("ward", list(Ward)),
        CheckConstraint("total >= 0 AND occupied >= 0 AND occupied <= total", name="ck_bed_counts"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"), index=True)
    ward: Mapped[str] = mapped_column(String(20))
    total: Mapped[int] = mapped_column(Integer)
    occupied: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))

    facility: Mapped[Facility] = relationship(back_populates="wards")


class AccessRequest(Base):
    """Someone who signed up asks for a role (and hospital); the coordinator approves or rejects."""

    __tablename__ = "access_requests"
    __table_args__ = (
        _enum_check("requested_role", list(Role)),
        _enum_check("status", ["PENDING", "APPROVED", "REJECTED"]),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    requested_role: Mapped[str] = mapped_column(String(20))
    facility_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"))
    name: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(300))  # e.g. "ASHA, Chakdaha block, ID 1234"
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    decided_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InviteCode(Base):
    """A secret joining code made by the coordinator. Whoever logs in with their own
    email and enters it gets that role (and hospital) straight away, without waiting."""

    __tablename__ = "invite_codes"
    __table_args__ = (_enum_check("role", list(Role)),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
    district: Mapped[str] = mapped_column(String(80), index=True)
    facility_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"))
    label: Mapped[str | None] = mapped_column(String(120))  # e.g. "Chakdaha block ASHAs, Oct training"
    max_uses: Mapped[int | None] = mapped_column(Integer)  # None = no limit
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
class BedHold(Base):
    """A bed reserved for one referral, from creation until arrival (or release)."""

    __tablename__ = "bed_holds"
    __table_args__ = (_enum_check("status", list(HoldStatus)), _enum_check("ward", list(Ward)))

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), unique=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    ward: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=HoldStatus.HELD, index=True)
    held_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AmbulanceTrip(Base):
    """The receiving hospital's ambulance fetching a referred patient."""

    __tablename__ = "ambulance_trips"
    __table_args__ = (_enum_check("status", list(AmbulanceStatus)),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=AmbulanceStatus.REQUESTED, index=True)
    pickup_note: Mapped[str] = mapped_column(String(300))  # village, landmark, how to find the house
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eta_minutes: Mapped[int | None] = mapped_column(Integer)
    vehicle_number: Mapped[str | None] = mapped_column(String(20))
    driver_phone: Mapped[str | None] = mapped_column(String(10))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
