"""Health-check schemas."""

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "unreachable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    uptime_s: float
    checks: dict[str, CheckStatus]


class LivenessResponse(BaseModel):
    status: Literal["ok"]
