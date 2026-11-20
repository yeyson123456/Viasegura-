"""Serves report photos from private storage (no public blob access needed)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.dependencies import get_storage
from app.errors import ApiError
from app.services.storage import MediaStorage, check_name

router = APIRouter(tags=["media"])


@router.get("/media/{name:path}", response_class=Response, summary="Privacy-filtered photo")
async def get_media(name: str, storage: Annotated[MediaStorage, Depends(get_storage)]) -> Response:
    try:
        check_name(name)
    except ValueError as exc:
        raise ApiError(404, "not_found", "Media not found") from exc
    data = await storage.load(name)
    if data is None:
        raise ApiError(404, "not_found", "Media not found")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )
