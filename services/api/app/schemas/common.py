"""Schemas shared by every endpoint."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

HazardType = Literal["pothole", "obstacle"]
IncidentStatus = Literal["pending", "confirmed", "resolved"]
HAZARD_TYPES: tuple[str, ...] = ("pothole", "obstacle")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone (e.g. 2026-11-20T10:00:00Z)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class ApiModel(BaseModel):
    """camelCase on the wire (as in the data model), snake_case in Python."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GeoPoint(BaseModel):
    """GeoJSON Point: coordinates are [longitude, latitude]."""

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def _check_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        lng, lat = value
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise ValueError("coordinates must be [longitude, latitude] within valid ranges")
        return value


class GeoLineString(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]] = Field(min_length=2)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Shape of every error returned by the API (see app/errors.py)."""

    error: ErrorDetail
