"""Response shapes sent to the frontend."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
