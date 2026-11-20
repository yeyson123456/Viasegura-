"""Explainable risk score per road segment (0-100).

    base   = 0.60 * incidents + 0.25 * rain + 0.15 * history        (each term in [0, 1])
    equity = 1 + 0.5 * isolationIndex                                  (up to +50 % priority)
    risk   = min(100, 100 * base * equity)

* incidents: confirmed, unresolved incidents on the segment; obstacles/landslides weigh 1.0 and
  potholes 0.5, halved every 7 days since last seen; normalised per 10 km and saturated.
* rain: precipitation of the last 72 h (Open-Meteo), saturating at 50 mm.
* history: mean risk of the segment over the last 30 days (persistence of chronic hotspots).
* equity rule: isolated communities get priority even with little traffic. Traffic volume is
  deliberately NOT a factor, so a quiet road that is the only access is never deprioritised.

Every score is stored with its breakdown so a road manager can see why a segment ranks high.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("viasegura.risk")

FORMULA_VERSION = "1.0"
WEIGHTS = {"incidents": 0.60, "rain": 0.25, "history": 0.15}
SEVERITY = {"obstacle": 1.0, "pothole": 0.5}
HALF_LIFE_DAYS = 7.0
RAIN_SATURATION_MM = 50.0
EQUITY_ALPHA = 0.5
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def incident_term(incidents: list[dict], now: datetime, length_km: float) -> float:
    load = 0.0
    for incident in incidents:
        age_days = max(0.0, (now - incident["lastSeen"]).total_seconds() / 86_400)
        load += SEVERITY.get(incident["type"], 0.5) * 0.5 ** (age_days / HALF_LIFE_DAYS)
    per_10km = load / max(length_km, 1.0) * 10.0
    return 1.0 - math.exp(-per_10km / 2.0)


def rain_term(rain_mm: float | None) -> float:
    return 0.0 if rain_mm is None else min(1.0, max(0.0, rain_mm) / RAIN_SATURATION_MM)


def score_segment(
    segment: dict, incidents: list[dict], rain_mm: float | None, history_mean: float | None,
    now: datetime,
) -> tuple[float, dict[str, Any]]:
    terms = {
        "incidents": incident_term(incidents, now, segment.get("lengthKm", 10.0)),
        "rain": rain_term(rain_mm),
        "history": min(1.0, (history_mean or 0.0) / 100.0),
    }
    base = sum(WEIGHTS[name] * value for name, value in terms.items())
    isolation = float(segment.get("isolationIndex", 0.0))
    equity = 1.0 + EQUITY_ALPHA * isolation
    score = round(min(100.0, 100.0 * base * equity), 2)
    breakdown = {
        "formulaVersion": FORMULA_VERSION,
        "terms": {k: round(v, 4) for k, v in terms.items()},
        "weights": WEIGHTS,
        "equityMultiplier": round(equity, 3),
        "isolationIndex": isolation,
        "confirmedIncidents": len(incidents),
        "rain72hMm": None if rain_mm is None else round(rain_mm, 1),
        "historyMean": None if history_mean is None else round(history_mean, 2),
    }
    return score, breakdown


def fetch_rain_72h(points: list[tuple[float, float]], timeout: float = 20) -> list[float | None]:
    """Precipitation of the last 72 h at each (lng, lat) from Open-Meteo (free, no key)."""
    if not points:
        return []
    query = (
        f"latitude={','.join(f'{lat:.4f}' for _, lat in points)}"
        f"&longitude={','.join(f'{lng:.4f}' for lng, _ in points)}"
        "&hourly=precipitation&past_days=3&forecast_days=1&timezone=UTC"
    )
    try:
        request = urllib.request.Request(
            f"{OPEN_METEO}?{query}", headers={"User-Agent": "viasegura-risk/1.0"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001 - rain is optional; the score still works
        logger.warning("rain_unavailable: %s", exc)
        return [None] * len(points)
    results = payload if isinstance(payload, list) else [payload]
    now = datetime.now(UTC).replace(tzinfo=None)
    totals: list[float | None] = []
    for result in results:
        hourly = result.get("hourly", {})
        total = 0.0
        for stamp, value in zip(hourly.get("time", []), hourly.get("precipitation", []), strict=False):
            moment = datetime.fromisoformat(stamp)
            if now - timedelta(hours=72) <= moment <= now and value is not None:
                total += float(value)
        totals.append(total)
    return totals


def recompute_all(db: Any, now: datetime | None = None, rain: bool = True) -> dict[str, Any]:
    """Recompute every segment, append to the risk_history time series, close pending events."""
    now = now or datetime.now(UTC)
    segments = list(db["segments"].find({}))
    midpoints = []
    for segment in segments:
        line = segment["geometry"]["coordinates"]
        midpoints.append(tuple(line[len(line) // 2]))
    rain_mm = fetch_rain_72h(midpoints) if rain else [None] * len(segments)

    since = now - timedelta(days=30)
    history = {
        row["_id"]: row["mean"]
        for row in db["risk_history"].aggregate(
            [
                {"$match": {"ts": {"$gte": since}}},
                {"$group": {"_id": "$meta.segmentId", "mean": {"$avg": "$riskScore"}}},
            ]
        )
    }
    incidents_by_segment: dict[Any, list[dict]] = {}
    for incident in db["incidents"].find({"status": "confirmed", "segmentId": {"$ne": None}}):
        incidents_by_segment.setdefault(incident["segmentId"], []).append(incident)

    history_docs = []
    for segment, segment_rain in zip(segments, rain_mm, strict=True):
        incidents = incidents_by_segment.get(segment["_id"], [])
        score, breakdown = score_segment(
            segment, incidents, segment_rain, history.get(segment["_id"]), now
        )
        db["segments"].update_one(
            {"_id": segment["_id"]},
            {"$set": {"riskScore": score, "riskBreakdown": breakdown, "updatedAt": now}},
        )
        history_docs.append(
            {
                "ts": now,
                "meta": {"segmentId": segment["_id"], "code": segment["code"]},
                "riskScore": score,
                "rain": segment_rain,
                "incidentCount": len(incidents),
            }
        )
    if history_docs:
        db["risk_history"].insert_many(history_docs)
    processed = db["events"].update_many(
        {"processedAt": None, "ts": {"$lte": now}}, {"$set": {"processedAt": now}}
    ).modified_count
    summary = {"segments": len(segments), "eventsProcessed": processed, "at": now.isoformat()}
    logger.info("risk_recomputed %s", summary)
    return summary
