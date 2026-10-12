"""Response shapes sent to the frontend."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service: str
    availability: str  # AVAILABLE | UNAVAILABLE | UNKNOWN
    availability_note: str | None
    availability_updated_at: datetime | None
    stale: bool  # True when the availability information is older than the stale limit


class FacilityOut(BaseModel):
    id: str
    name: str
    type: str
    district: str
    phone: str | None
    beds: int | None
    services: list[ServiceOut]


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
