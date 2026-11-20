"""Schema checks against a real MongoDB (skipped when none is reachable, see conftest)."""

import pytest

pytestmark = pytest.mark.integration


async def test_health_reports_schema_ready(api) -> None:
    http, _ = api

    response = await http.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["checks"] == {"database": "ok"}
    assert body["components"]["schema"] == "ready"


async def test_indexes_ttl_and_time_series_exist(api) -> None:
    _, app = api
    db = app.state.mongo.db

    report_indexes = await db["reports"].index_information()
    incident_indexes = await db["incidents"].index_information()
    segment_indexes = await db["segments"].index_information()
    collections = {c["name"]: c async for c in await db.list_collections()}

    assert report_indexes["location_2dsphere"]["key"] == [("location", "2dsphere")]
    assert report_indexes["reports_ttl"]["expireAfterSeconds"] == 30 * 86_400
    assert report_indexes["device_report_unique"]["unique"] is True
    assert incident_indexes["status_type"]["key"] == [("status", 1), ("type", 1)]
    assert "location_2dsphere" in incident_indexes
    assert "geometry_2dsphere" in segment_indexes
    assert collections["risk_history"]["type"] == "timeseries"


async def test_ttl_change_is_applied_in_place(api) -> None:
    from app.db import ensure_schema

    _, app = api
    db = app.state.mongo.db

    await ensure_schema(db, reports_ttl_days=7, seed_segments=False)

    assert (await db["reports"].index_information())["reports_ttl"][
        "expireAfterSeconds"
    ] == 7 * 86_400


async def test_segments_are_seeded_and_ranked(api) -> None:
    http, _ = api

    response = await http.get("/segments/risk", params={"limit": 50})

    assert response.status_code == 200
    segments = response.json()
    assert len(segments) == 13
    first = segments[0]
    assert first["code"].startswith("HCO-TGM-")
    assert first["geometry"]["type"] == "LineString"
    assert {"populationServed", "isolationIndex", "riskScore", "lengthKm"} <= first.keys()


async def test_stats_shape(api) -> None:
    http, _ = api

    response = await http.get("/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["segments"] == 13
    assert body["consensus"] == {"minDevices": 3, "radiusM": 30.0, "windowMin": 60.0}
    assert set(body["incidentsByStatus"]) == {"pending", "confirmed", "resolved"}
    assert body["reportsLast24h"] == 0
