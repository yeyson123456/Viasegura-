"""Health endpoints: readiness (/health) and liveness (/health/live)."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app import __version__
from app.db import Mongo, get_mongo
from app.schemas.health import HealthResponse, LivenessResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is unreachable"}},
)
async def health(
    request: Request,
    response: Response,
    mongo: Annotated[Mongo, Depends(get_mongo)],
) -> HealthResponse:
    """Readiness check: 200 when the database answers a ping, 503 otherwise."""
    database_ok = await mongo.ping()
    response.headers["Cache-Control"] = "no-store"
    if not database_ok:
        response.status_code = 503
    state = request.app.state
    detector = getattr(state, "detector", None)
    storage = getattr(state, "storage", None)
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        version=__version__,
        environment=state.settings.api_env,
        uptime_s=round(time.monotonic() - state.started_at, 3),
        checks={"database": "ok" if database_ok else "unreachable"},
        components={
            "schema": "ready" if getattr(state, "schema_ready", False) else "pending",
            "detector": f"loaded:{detector.version}" if detector else "disabled",
            "storage": type(storage).__name__ if storage else "none",
        },
    )


@router.get("/health/live", response_model=LivenessResponse)
async def liveness(response: Response) -> LivenessResponse:
    """Liveness check: the process is up. Never touches external dependencies."""
    response.headers["Cache-Control"] = "no-store"
    return LivenessResponse(status="ok")
