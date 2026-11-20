"""MongoDB access through the PyMongo Async API (Motor's official successor, docs/decisions.md)."""

import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from pymongo import AsyncMongoClient
from pymongo.errors import CollectionInvalid, PyMongoError

from app.services.geo import line_length_km

logger = logging.getLogger("viasegura.db")

SEED_SEGMENTS = Path(__file__).resolve().parent.parent / "seed" / "segments.geojson"


class Mongo:
    """Owns the MongoDB client for the lifetime of the application."""

    def __init__(self, uri: str, db_name: str, timeout_ms: int) -> None:
        # The async client connects lazily, so constructing it never blocks start-up.
        self.client: AsyncMongoClient = AsyncMongoClient(
            uri,
            appname="viasegura-api",
            tz_aware=True,
            serverSelectionTimeoutMS=timeout_ms,
            connectTimeoutMS=timeout_ms,
        )
        self.db = self.client[db_name]

    async def ping(self) -> bool:
        try:
            await self.client.admin.command("ping")
        except PyMongoError as exc:
            logger.warning("mongodb_unreachable", extra={"error": str(exc)[:300]})
            return False
        return True

    async def close(self) -> None:
        await self.client.close()


def get_mongo(request: Request) -> Mongo:
    """FastAPI dependency; tests override it with a fake."""
    return request.app.state.mongo


async def _ensure_ttl(db: Any, collection: str, field: str, seconds: int, name: str) -> None:
    """Create the TTL index, or update its expiry in place when the setting changed."""
    current = (await db[collection].index_information()).get(name)
    if current is None:
        await db[collection].create_index([(field, 1)], name=name, expireAfterSeconds=seconds)
    elif current.get("expireAfterSeconds") != seconds:
        await db.command(
            {"collMod": collection, "index": {"name": name, "expireAfterSeconds": seconds}}
        )
        logger.info("ttl_updated", extra={"collection": collection, "seconds": seconds})


async def ensure_schema(db: Any, reports_ttl_days: int, seed_segments: bool = True) -> None:
    """Idempotent: indexes, time-series collection and seed data."""
    reports = db["reports"]
    await reports.create_index([("location", "2dsphere")], name="location_2dsphere")
    await reports.create_index(
        [("deviceId", 1), ("clientReportId", 1)], unique=True, name="device_report_unique"
    )
    await reports.create_index([("type", 1), ("ts", -1)], name="type_ts")
    await reports.create_index([("incidentId", 1), ("ts", 1)], name="incident_ts")
    await _ensure_ttl(db, "reports", "receivedAt", reports_ttl_days * 86_400, "reports_ttl")

    incidents = db["incidents"]
    await incidents.create_index([("location", "2dsphere")], name="location_2dsphere")
    await incidents.create_index([("status", 1), ("type", 1)], name="status_type")
    await incidents.create_index([("lastSeen", -1)], name="last_seen")
    await incidents.create_index([("segmentId", 1), ("status", 1)], name="segment_status")

    segments = db["segments"]
    await segments.create_index([("geometry", "2dsphere")], name="geometry_2dsphere")
    await segments.create_index([("code", 1)], unique=True, name="code_unique")
    await segments.create_index([("riskScore", -1)], name="risk_desc")

    await db["events"].create_index([("processedAt", 1), ("ts", 1)], name="unprocessed")

    with contextlib.suppress(CollectionInvalid):  # already exists
        await db.create_collection(
            "risk_history",
            timeseries={"timeField": "ts", "metaField": "meta", "granularity": "hours"},
        )

    if seed_segments and await segments.count_documents({}) == 0 and SEED_SEGMENTS.exists():
        documents = load_seed_segments(SEED_SEGMENTS)
        if documents:
            await segments.insert_many(documents)
            logger.info("segments_seeded", extra={"count": len(documents)})


def load_seed_segments(path: Path) -> list[dict[str, Any]]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    documents = []
    for feature in collection["features"]:
        props = feature["properties"]
        coordinates = feature["geometry"]["coordinates"]
        documents.append(
            {
                "code": props["code"],
                "name": props["name"],
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "lengthKm": round(line_length_km(coordinates), 2),
                "populationServed": int(props["populationServed"]),
                "isolationIndex": float(props["isolationIndex"]),
                "trafficLevel": props.get("trafficLevel"),
                "sources": props.get("sources"),
                "riskScore": 0.0,
                "riskBreakdown": None,
                "updatedAt": now,
            }
        )
    return documents
