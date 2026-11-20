"""Road segments ranked by risk, plus overall statistics for the dashboard."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from app.config import Settings
from app.dependencies import get_app_settings, get_db
from app.schemas.common import HAZARD_TYPES
from app.schemas.segments import SegmentOut, StatsOut

router = APIRouter(tags=["segments"])


async def _open_incidents_by_segment(db: Any) -> dict[Any, int]:
    cursor = await db["incidents"].aggregate(
        [
            {"$match": {"status": "confirmed", "segmentId": {"$ne": None}}},
            {"$group": {"_id": "$segmentId", "count": {"$sum": 1}}},
        ]
    )
    return {row["_id"]: row["count"] async for row in cursor}


@router.get(
    "/segments/risk",
    response_model=list[SegmentOut],
    summary="Road segments ordered by risk score (highest first)",
)
async def segments_by_risk(
    response: Response,
    db: Annotated[Any, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 10,
) -> list[SegmentOut]:
    open_counts = await _open_incidents_by_segment(db)
    cursor = db["segments"].find({}).sort([("riskScore", -1), ("code", 1)]).limit(limit)
    response.headers["Cache-Control"] = "no-store"
    return [
        SegmentOut(
            id=str(document["_id"]),
            code=document["code"],
            name=document["name"],
            geometry=document["geometry"],
            length_km=document.get("lengthKm", 0.0),
            risk_score=round(float(document.get("riskScore", 0.0)), 2),
            risk_breakdown=document.get("riskBreakdown"),
            population_served=document.get("populationServed", 0),
            isolation_index=document.get("isolationIndex", 0.0),
            traffic_level=document.get("trafficLevel"),
            open_incidents=open_counts.get(document["_id"], 0),
            updated_at=document.get("updatedAt"),
        )
        async for document in cursor
    ]


@router.get("/stats", response_model=StatsOut, summary="Headline numbers for the dashboard")
async def stats(
    response: Response,
    db: Annotated[Any, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> StatsOut:
    since = datetime.now(UTC) - timedelta(hours=24)
    by_status = {status: 0 for status in ("pending", "confirmed", "resolved")}
    confirmed_by_type = dict.fromkeys(HAZARD_TYPES, 0)
    cursor = await db["incidents"].aggregate(
        [{"$group": {"_id": {"status": "$status", "type": "$type"}, "count": {"$sum": 1}}}]
    )
    async for row in cursor:
        status, hazard = row["_id"]["status"], row["_id"]["type"]
        by_status[status] = by_status.get(status, 0) + row["count"]
        if status == "confirmed":
            confirmed_by_type[hazard] = confirmed_by_type.get(hazard, 0) + row["count"]
    latest = await db["segments"].find_one(
        {"riskBreakdown": {"$ne": None}}, sort=[("updatedAt", -1)]
    )
    response.headers["Cache-Control"] = "no-store"
    return StatsOut(
        reports_last_24h=await db["reports"].count_documents({"receivedAt": {"$gte": since}}),
        incidents_by_status=by_status,
        confirmed_by_type=confirmed_by_type,
        segments=await db["segments"].count_documents({}),
        last_risk_update=latest["updatedAt"] if latest else None,
        consensus={
            "minDevices": settings.consensus_min_devices,
            "radiusM": settings.consensus_radius_m,
            "windowMin": settings.consensus_window_min,
        },
    )
