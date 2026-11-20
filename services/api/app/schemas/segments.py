"""Road segment and statistics schemas."""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel, GeoLineString


class SegmentOut(ApiModel):
    id: str
    code: str
    name: str
    geometry: GeoLineString
    length_km: float
    risk_score: float
    risk_breakdown: dict[str, Any] | None = None
    population_served: int
    isolation_index: float
    traffic_level: str | None = None
    open_incidents: int = 0
    updated_at: datetime | None = None


class StatsOut(ApiModel):
    # Explicit alias: the camelCase generator would produce "reportsLast24H".
    reports_last_24h: int = Field(alias="reportsLast24h")
    incidents_by_status: dict[str, int]
    confirmed_by_type: dict[str, int]
    segments: int
    last_risk_update: datetime | None
    consensus: dict[str, float]
