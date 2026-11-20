"""Incident endpoints: nearby (drivers), list (dashboard) and resolve (road managers)."""

from typing import Annotated, Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Query, Response

from app.dependencies import get_consensus, get_db, require_admin
from app.errors import ApiError
from app.schemas.common import HazardType, IncidentStatus
from app.schemas.incidents import IncidentOut, IncidentUpdate
from app.services.consensus import ConsensusService

router = APIRouter(tags=["incidents"])

_BBOX = r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$"


def incident_out(document: dict[str, Any]) -> IncidentOut:
    segment_id = document.get("segmentId")
    distance = document.get("distanceM")
    return IncidentOut(
        id=str(document["_id"]),
        type=document["type"],
        status=document["status"],
        location=document["location"],
        reports_count=document.get("reportsCount", 0),
        devices_count=len(document.get("devices", [])),
        max_confidence=round(float(document.get("maxConfidence", 0.0)), 4),
        first_seen=document["firstSeen"],
        last_seen=document["lastSeen"],
        confirmed_at=document.get("confirmedAt"),
        resolved_at=document.get("resolvedAt"),
        image_url=document.get("imageUrl"),
        segment_id=str(segment_id) if segment_id else None,
        segment_name=document.get("segmentName"),
        distance_m=round(distance, 1) if distance is not None else None,
    )


@router.get(
    "/incidents/nearby",
    response_model=list[IncidentOut],
    summary="Confirmed incidents around a point, nearest first (driver alerts)",
)
async def nearby_incidents(
    response: Response,
    db: Annotated[Any, Depends(get_db)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    radius: Annotated[float, Query(gt=0, le=50_000, description="metres")] = 2_000,
    type: Annotated[HazardType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[IncidentOut]:
    query: dict[str, Any] = {"status": "confirmed"}
    if type:
        query["type"] = type
    cursor = await db["incidents"].aggregate(
        [
            {
                "$geoNear": {
                    "near": {"type": "Point", "coordinates": [lng, lat]},
                    "key": "location",
                    "distanceField": "distanceM",
                    "maxDistance": radius,
                    "spherical": True,
                    "query": query,
                }
            },
            {"$limit": limit},
        ]
    )
    response.headers["Cache-Control"] = "no-store"
    return [incident_out(document) async for document in cursor]


@router.get(
    "/incidents",
    response_model=list[IncidentOut],
    summary="Incidents for the dashboard (any status), most recent first",
)
async def list_incidents(
    response: Response,
    db: Annotated[Any, Depends(get_db)],
    status: Annotated[list[IncidentStatus] | None, Query()] = None,
    type: Annotated[HazardType | None, Query()] = None,
    bbox: Annotated[
        str | None, Query(pattern=_BBOX, description="minLng,minLat,maxLng,maxLat")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=2_000)] = 500,
) -> list[IncidentOut]:
    query: dict[str, Any] = {}
    if status:
        query["status"] = {"$in": status}
    if type:
        query["type"] = type
    if bbox:
        min_lng, min_lat, max_lng, max_lat = map(float, bbox.split(","))
        if not (min_lng < max_lng and min_lat < max_lat):
            raise ApiError(422, "validation_error", "bbox must be minLng,minLat,maxLng,maxLat")
        ring = [
            [min_lng, min_lat],
            [max_lng, min_lat],
            [max_lng, max_lat],
            [min_lng, max_lat],
            [min_lng, min_lat],
        ]
        query["location"] = {
            "$geoWithin": {"$geometry": {"type": "Polygon", "coordinates": [ring]}}
        }
    cursor = db["incidents"].find(query).sort("lastSeen", -1).limit(limit)
    response.headers["Cache-Control"] = "no-store"
    return [incident_out(document) async for document in cursor]


@router.patch(
    "/incidents/{incident_id}",
    response_model=IncidentOut,
    dependencies=[Depends(require_admin)],
    summary="Mark an incident as resolved (requires X-Admin-Key)",
)
async def update_incident(
    incident_id: str,
    body: IncidentUpdate,
    db: Annotated[Any, Depends(get_db)],
    consensus: Annotated[ConsensusService, Depends(get_consensus)],
) -> IncidentOut:
    try:
        object_id = ObjectId(incident_id)
    except InvalidId as exc:
        raise ApiError(404, "not_found", "Incident not found") from exc
    document = await consensus.resolve(object_id, body.note)
    if document is None:  # unknown, or already resolved (idempotent)
        document = await db["incidents"].find_one({"_id": object_id})
        if document is None:
            raise ApiError(404, "not_found", "Incident not found")
    return incident_out(document)
