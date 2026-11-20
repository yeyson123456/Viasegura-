"""Reports, consensus (N=3 devices, R=30 m, T=60 min) and incident life cycle on a real MongoDB."""

import io
import json
import math
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

pytestmark = pytest.mark.integration

ADMIN_KEY = "test-admin-key"  # same value the `api` fixture configures

SEED = Path(__file__).resolve().parent.parent / "seed" / "segments.geojson"


def _point_on_segment(code: str) -> tuple[float, float]:
    features = json.loads(SEED.read_text(encoding="utf-8"))["features"]
    line = next(f for f in features if f["properties"]["code"] == code)["geometry"]["coordinates"]
    lng, lat = line[len(line) // 2]
    return lng, lat


# A real point on the corridor (segment 05, Chinchao district).
BASE_LNG, BASE_LAT = _point_on_segment("HCO-TGM-05")


def offset(lng: float, lat: float, east_m: float, north_m: float) -> tuple[float, float]:
    d_lat = north_m / 111_320
    d_lng = east_m / (111_320 * math.cos(math.radians(lat)))
    return lng + d_lng, lat + d_lat


def report(
    device: str,
    *,
    east_m: float = 0,
    north_m: float = 0,
    hazard: str = "pothole",
    minutes_ago: float = 1,
    confidence: float = 0.8,
    client_id: str | None = None,
) -> dict:
    lng, lat = offset(BASE_LNG, BASE_LAT, east_m, north_m)
    return {
        "clientReportId": client_id or str(uuid.uuid4()),
        "deviceId": device,
        "type": hazard,
        "confidence": confidence,
        "location": {"type": "Point", "coordinates": [lng, lat]},
        "accuracyM": 6.0,
        "ts": (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat(),
    }


async def post(http, payload: dict):
    return await http.post("/reports", json=payload)


async def test_first_report_opens_pending_incident_linked_to_segment(api) -> None:
    http, app = api

    response = await post(http, report("device-aaaa-0001"))

    assert response.status_code == 201
    body = response.json()
    assert body["accepted"] is True
    assert body["incidentStatus"] == "pending"
    assert body["distinctDevices"] == 1
    assert body["requiredDevices"] == 3
    assert body["serverCheck"]["status"] == "skipped"
    incident = await app.state.mongo.db["incidents"].find_one({})
    assert incident["segmentName"] and incident["segmentName"].startswith("Tramo")


async def test_three_distinct_devices_confirm_and_emit_one_event(api) -> None:
    http, app = api

    statuses = []
    for index, (east, north) in enumerate([(0, 0), (8, -5), (-6, 9)]):
        response = await post(http, report(f"device-bbbb-000{index}", east_m=east, north_m=north))
        statuses.append(response.json()["incidentStatus"])
    late = await post(http, report("device-bbbb-0009", east_m=3, north_m=3))

    assert statuses == ["pending", "pending", "confirmed"]
    assert late.json()["incidentStatus"] == "confirmed"
    db = app.state.mongo.db
    assert await db["incidents"].count_documents({}) == 1
    assert await db["events"].count_documents({"type": "incident_confirmed"}) == 1
    incident = await db["incidents"].find_one({})
    assert incident["reportsCount"] == 4
    # The incident position is the running mean of the reports (stays within a few metres).
    lng, lat = incident["location"]["coordinates"]
    assert abs(lng - BASE_LNG) < 0.0001 and abs(lat - BASE_LAT) < 0.0001

    nearby = await http.get("/incidents/nearby", params={"lng": BASE_LNG, "lat": BASE_LAT})
    assert nearby.status_code == 200
    [found] = nearby.json()
    assert found["status"] == "confirmed"
    assert found["devicesCount"] == 4
    assert found["distanceM"] < 30
    assert "devices" not in found  # device ids are never exposed


async def test_one_device_reporting_many_times_does_not_confirm(api) -> None:
    http, _ = api

    for _ in range(4):
        response = await post(http, report("device-cccc-0001"))

    assert response.json()["incidentStatus"] == "pending"
    assert response.json()["distinctDevices"] == 1


async def test_reports_farther_than_radius_open_separate_incidents(api) -> None:
    http, app = api

    await post(http, report("device-dddd-0001"))
    await post(http, report("device-dddd-0002", east_m=80))

    assert await app.state.mongo.db["incidents"].count_documents({}) == 2


async def test_different_hazard_types_do_not_merge(api) -> None:
    http, app = api

    await post(http, report("device-eeee-0001", hazard="pothole"))
    await post(http, report("device-eeee-0002", hazard="obstacle"))

    assert await app.state.mongo.db["incidents"].count_documents({}) == 2


async def test_reports_outside_time_window_do_not_confirm(api) -> None:
    http, _ = api

    await post(http, report("device-ffff-0001", minutes_ago=200))
    await post(http, report("device-ffff-0002", minutes_ago=100))
    response = await post(http, report("device-ffff-0003", minutes_ago=1))

    # Each pair is more than 60 min apart, so no 60-minute window holds three devices.
    assert response.json()["incidentStatus"] == "pending"


async def test_retried_report_is_idempotent(api) -> None:
    http, app = api
    payload = report("device-gggg-0001", client_id="retry-0000-0001")

    first = await post(http, payload)
    second = await post(http, payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["reportId"] == first.json()["reportId"]
    assert await app.state.mongo.db["reports"].count_documents({}) == 1


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"confidence": 0.05}, "low_confidence"),
        ({"ts": (datetime.now(UTC) + timedelta(hours=2)).isoformat()}, "timestamp_in_future"),
        ({"ts": (datetime.now(UTC) - timedelta(days=5)).isoformat()}, "timestamp_too_old"),
        ({"location": {"type": "Point", "coordinates": [200, 0]}}, "validation_error"),
        ({"type": "cow"}, "validation_error"),
        ({"ts": "2026-11-20T10:00:00"}, "validation_error"),  # no timezone
    ],
)
async def test_invalid_reports_are_refused(api, changes: dict, code: str) -> None:
    http, _ = api

    response = await post(http, {**report("device-hhhh-0001"), **changes})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


async def test_multipart_report_stores_metadata_free_photo(api) -> None:
    http, app = api
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make, must not survive re-encoding
    Image.new("RGB", (320, 240), (120, 120, 120)).save(buffer, "JPEG", exif=exif.tobytes())

    response = await http.post(
        "/reports",
        data={"report": json.dumps(report("device-iiii-0001"))},
        files={"image": ("hazard.jpg", buffer.getvalue(), "image/jpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["serverCheck"] == {
        "status": "skipped",
        "confidence": None,
        "reason": "detector_unavailable",
    }
    media = await http.get(body["imageUrl"])
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/jpeg"
    stored = Image.open(io.BytesIO(media.content))
    assert dict(stored.getexif()) == {}
    incident = await app.state.mongo.db["incidents"].find_one({})
    assert incident["imageUrl"] == body["imageUrl"]


async def test_non_image_upload_is_refused(api) -> None:
    http, _ = api

    response = await http.post(
        "/reports",
        data={"report": json.dumps(report("device-jjjj-0001"))},
        files={"image": ("x.jpg", b"not an image at all", "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_image"


async def test_resolve_requires_admin_key_and_reopens_as_new_incident(api) -> None:
    http, app = api
    for index in range(3):
        last = await post(http, report(f"device-kkkk-000{index}"))
    incident_id = last.json()["incidentId"]

    no_key = await http.patch(f"/incidents/{incident_id}", json={"status": "resolved"})
    wrong = await http.patch(
        f"/incidents/{incident_id}", json={"status": "resolved"}, headers={"X-Admin-Key": "nope"}
    )
    ok = await http.patch(
        f"/incidents/{incident_id}",
        json={"status": "resolved", "note": "Cuadrilla reparó el bache"},
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    nearby = await http.get("/incidents/nearby", params={"lng": BASE_LNG, "lat": BASE_LAT})
    again = await post(http, report("device-kkkk-0009"))

    assert no_key.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["status"] == "resolved"
    assert nearby.json() == []
    assert again.json()["incidentStatus"] == "pending"
    assert again.json()["incidentId"] != incident_id
    events = app.state.mongo.db["events"]
    assert await events.count_documents({"type": "incident_resolved"}) == 1


async def test_list_incidents_filters_by_status_and_bbox(api) -> None:
    http, _ = api
    await post(http, report("device-llll-0001"))
    for index in range(3):
        await post(http, report(f"device-llll-01{index}", east_m=500))

    pending = await http.get("/incidents", params={"status": "pending"})
    confirmed = await http.get("/incidents", params={"status": "confirmed"})
    far_box = await http.get("/incidents", params={"bbox": "-70.1,-12.1,-70.0,-12.0"})

    assert [i["status"] for i in pending.json()] == ["pending"]
    assert [i["status"] for i in confirmed.json()] == ["confirmed"]
    assert far_box.json() == []
