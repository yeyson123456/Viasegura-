"""Incident schemas. Device ids are stored but never exposed (privacy)."""

from datetime import datetime
from typing import Literal

from app.schemas.common import ApiModel, GeoPoint, HazardType, IncidentStatus


class IncidentOut(ApiModel):
    id: str
    type: HazardType
    status: IncidentStatus
    location: GeoPoint
    reports_count: int
    devices_count: int
    max_confidence: float
    first_seen: datetime
    last_seen: datetime
    confirmed_at: datetime | None = None
    resolved_at: datetime | None = None
    image_url: str | None = None
    segment_id: str | None = None
    segment_name: str | None = None
    distance_m: float | None = None


class IncidentUpdate(ApiModel):
    status: Literal["resolved"]
    note: str | None = None
