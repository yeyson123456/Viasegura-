"""Report schemas: what a phone sends and what the API answers."""

from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel, GeoPoint, HazardType, IncidentStatus, UtcDatetime

_ID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"


class ReportIn(ApiModel):
    """A hazard detected on a phone. Sent as JSON, or as the `report` field of a multipart form
    whose optional `image` field carries the privacy-filtered photo."""

    client_report_id: str = Field(
        pattern=_ID_PATTERN, description="UUID made by the phone; retries are idempotent"
    )
    device_id: str = Field(pattern=_ID_PATTERN, description="Anonymous, rotating device id")
    type: HazardType
    confidence: float = Field(ge=0, le=1)
    location: GeoPoint
    accuracy_m: float | None = Field(default=None, ge=0, le=10_000)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    speed_kmh: float | None = Field(default=None, ge=0, le=300)
    ts: UtcDatetime = Field(description="Capture time on the device (ISO 8601 with timezone)")
    model_version: str | None = Field(default=None, max_length=80)


class ServerCheck(ApiModel):
    status: Literal["confirmed", "rejected", "skipped"]
    confidence: float | None = None
    reason: str | None = None


class ReportResult(ApiModel):
    report_id: str
    duplicate: bool
    accepted: bool
    incident_id: str | None
    incident_status: IncidentStatus | None
    distinct_devices: int
    required_devices: int
    server_check: ServerCheck
    image_url: str | None = None
