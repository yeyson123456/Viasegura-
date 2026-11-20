"""Health-check schemas."""

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "unreachable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    uptime_s: float
    # Checks decide the HTTP status (200 / 503).
    checks: dict[str, CheckStatus]
    # Informational: schema readiness, detector and storage backend.
    components: dict[str, str] = {}


class LivenessResponse(BaseModel):
    status: Literal["ok"]
