"""FastAPI dependencies that hand out the services created in the application lifespan."""

import hmac
from typing import Annotated

from fastapi import Depends, Header, Request

from app.config import Settings
from app.errors import ApiError
from app.services.consensus import ConsensusService
from app.services.detector import HazardDetector
from app.services.storage import MediaStorage


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request):
    return request.app.state.mongo.db


def get_consensus(request: Request) -> ConsensusService:
    return request.app.state.consensus


def get_detector(request: Request) -> HazardDetector | None:
    return request.app.state.detector


def get_storage(request: Request) -> MediaStorage:
    return request.app.state.storage


def require_admin(
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    """Admin actions need the X-Admin-Key header (compared in constant time)."""
    if not settings.admin_api_key:
        raise ApiError(503, "admin_disabled", "Admin actions are disabled (ADMIN_API_KEY unset)")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise ApiError(401, "unauthorized", "Missing or invalid X-Admin-Key header")
