"""Consensus: a hazard becomes a *confirmed* incident when N distinct devices report the same
type within R metres and T minutes. N, R and T come from settings (environment variables)."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument

from app.services.events import EventPublisher

logger = logging.getLogger("viasegura.consensus")

OPEN_STATUSES = ["pending", "confirmed"]


@dataclass(frozen=True)
class ConsensusRules:
    min_devices: int
    radius_m: float
    window: timedelta
    segment_radius_m: float


@dataclass(frozen=True)
class ConsensusOutcome:
    incident_id: ObjectId
    status: str
    distinct_devices: int
    newly_confirmed: bool


def _moved_coordinate(index: int, value: float, count_after: dict) -> dict:
    """Running mean of the incident position: old + (new - old) / count."""
    current = {"$arrayElemAt": ["$location.coordinates", index]}
    return {"$add": [current, {"$divide": [{"$subtract": [value, current]}, count_after]}]}


class ConsensusService:
    def __init__(self, db: Any, rules: ConsensusRules, events: EventPublisher) -> None:
        self.reports = db["reports"]
        self.incidents = db["incidents"]
        self.segments = db["segments"]
        self.rules = rules
        self.events = events
        # Serialises find-or-create per hazard type inside this process. With several API
        # replicas two simultaneous *first* reports could still open two incidents (README).
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def process(self, report: dict[str, Any]) -> ConsensusOutcome:
        async with self._locks[report["type"]]:
            incident = await self.incidents.find_one(
                {
                    "type": report["type"],
                    "status": {"$in": OPEN_STATUSES},
                    "location": {
                        "$nearSphere": {
                            "$geometry": report["location"],
                            "$maxDistance": self.rules.radius_m,
                        }
                    },
                }
            )
            if incident is None:
                incident = await self._open_incident(report)
            else:
                incident = await self._attach(incident["_id"], report)
        await self.reports.update_one(
            {"_id": report["_id"]}, {"$set": {"incidentId": incident["_id"]}}
        )

        devices = await self.distinct_devices(incident["_id"], report["ts"])
        status, newly_confirmed = incident["status"], False
        if status == "pending" and len(devices) >= self.rules.min_devices:
            # Conditional transition: only one concurrent request can confirm the incident.
            result = await self.incidents.update_one(
                {"_id": incident["_id"], "status": "pending"},
                {"$set": {"status": "confirmed", "confirmedAt": datetime.now(UTC)}},
            )
            if result.modified_count:
                status, newly_confirmed = "confirmed", True
                await self.events.publish("incident_confirmed", self._event_payload(incident))
                logger.info(
                    "incident_confirmed",
                    extra={"incident_id": str(incident["_id"]), "devices": len(devices)},
                )
            else:
                fresh = await self.incidents.find_one({"_id": incident["_id"]}, {"status": 1})
                status = fresh["status"] if fresh else status
        return ConsensusOutcome(incident["_id"], status, len(devices), newly_confirmed)

    async def distinct_devices(self, incident_id: ObjectId, ts: datetime) -> list[str]:
        """Devices whose accepted reports of this incident fall within +/- T minutes of `ts`.

        A report only joins an open incident of the same type within R metres, so this enforces
        the "N devices, R metres, T minutes" rule while ignoring reports of earlier, resolved
        incidents at the same place. The window is centred on the capture time, so reports
        synced late from an offline queue are judged by when the hazard was seen.
        """
        return await self.reports.distinct(
            "deviceId",
            {
                "incidentId": incident_id,
                "accepted": True,
                "ts": {"$gte": ts - self.rules.window, "$lte": ts + self.rules.window},
            },
        )

    async def resolve(self, incident_id: ObjectId, note: str | None) -> dict | None:
        incident = await self.incidents.find_one_and_update(
            {"_id": incident_id, "status": {"$ne": "resolved"}},
            {
                "$set": {
                    "status": "resolved",
                    "resolvedAt": datetime.now(UTC),
                    "resolutionNote": note,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if incident is not None:
            await self.events.publish("incident_resolved", self._event_payload(incident))
        return incident

    async def _open_incident(self, report: dict[str, Any]) -> dict[str, Any]:
        segment = await self.segments.find_one(
            {
                "geometry": {
                    "$nearSphere": {
                        "$geometry": report["location"],
                        "$maxDistance": self.rules.segment_radius_m,
                    }
                }
            },
            {"name": 1},
        )
        incident = {
            "type": report["type"],
            "status": "pending",
            "location": report["location"],
            "reportsCount": 1,
            "devices": [report["deviceId"]],
            "maxConfidence": report["confidence"],
            "firstSeen": report["ts"],
            "lastSeen": report["ts"],
            "imageUrl": report.get("imageUrl"),
            "segmentId": segment["_id"] if segment else None,
            "segmentName": segment["name"] if segment else None,
            "createdAt": datetime.now(UTC),
        }
        result = await self.incidents.insert_one(incident)
        incident["_id"] = result.inserted_id
        return incident

    async def _attach(self, incident_id: ObjectId, report: dict[str, Any]) -> dict[str, Any]:
        lng, lat = report["location"]["coordinates"]
        count_after = {"$add": ["$reportsCount", 1]}
        update = [
            {
                "$set": {
                    "location": {
                        "type": "Point",
                        "coordinates": [
                            _moved_coordinate(0, lng, count_after),
                            _moved_coordinate(1, lat, count_after),
                        ],
                    },
                    "reportsCount": count_after,
                    "devices": {"$setUnion": ["$devices", [{"$literal": report["deviceId"]}]]},
                    "maxConfidence": {"$max": ["$maxConfidence", report["confidence"]]},
                    "lastSeen": {"$max": ["$lastSeen", report["ts"]]},
                    "firstSeen": {"$min": ["$firstSeen", report["ts"]]},
                    "imageUrl": {"$ifNull": [{"$literal": report.get("imageUrl")}, "$imageUrl"]},
                }
            }
        ]
        return await self.incidents.find_one_and_update(
            {"_id": incident_id}, update, return_document=ReturnDocument.AFTER
        )

    @staticmethod
    def _event_payload(incident: dict[str, Any]) -> dict[str, Any]:
        segment_id = incident.get("segmentId")
        return {
            "incidentId": str(incident["_id"]),
            "segmentId": str(segment_id) if segment_id else None,
            "hazardType": incident["type"],
            "location": incident["location"],
        }
