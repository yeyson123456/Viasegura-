"""Schemas shared by every endpoint."""

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Shape of every error returned by the API (see app/errors.py)."""

    error: ErrorDetail
