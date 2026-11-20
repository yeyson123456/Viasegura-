"""Simulate several phones reporting the same hazard, to watch consensus happen.

Each simulated device reports the hazard with a few metres of GPS noise. With the default
consensus (N=3), the third device confirms the incident, which then appears in
GET /incidents/nearby and in the dashboard.

Usage (standard library only):
    python scripts/simulate_reports.py                       # 3 devices, pothole, segment 05
    python scripts/simulate_reports.py --devices 4 --type obstacle --segment HCO-TGM-06
    python scripts/simulate_reports.py --lng -76.09 --lat -9.70 --api https://<your-api>
"""

from __future__ import annotations

import argparse
import json
import math
import random
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime


def call(method: str, url: str, payload: dict | None = None) -> tuple[int, dict | list]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def point_on_segment(api: str, code: str) -> tuple[float, float]:
    _, segments = call("GET", f"{api}/segments/risk?limit=500")
    segment = next((s for s in segments if s["code"] == code), None)
    if segment is None:
        raise SystemExit(f"segment {code} not found; available: {[s['code'] for s in segments]}")
    line = segment["geometry"]["coordinates"]
    return tuple(line[len(line) // 2])  # type: ignore[return-value]


def jitter(lng: float, lat: float, metres: float) -> tuple[float, float]:
    angle, distance = random.uniform(0, 2 * math.pi), random.uniform(0, metres)
    d_lat = distance * math.sin(angle) / 111_320
    d_lng = distance * math.cos(angle) / (111_320 * math.cos(math.radians(lat)))
    return lng + d_lng, lat + d_lat


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--devices", type=int, default=3)
    parser.add_argument("--type", default="pothole", choices=["pothole", "obstacle"])
    parser.add_argument("--segment", default="HCO-TGM-05")
    parser.add_argument("--lng", type=float)
    parser.add_argument("--lat", type=float)
    parser.add_argument("--noise-m", type=float, default=8.0, help="GPS noise radius")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    if args.lng is not None and args.lat is not None:
        lng, lat = args.lng, args.lat
    else:
        lng, lat = point_on_segment(api, args.segment)
    print(f"Hazard '{args.type}' at lng={lng:.6f} lat={lat:.6f}\n")

    for index in range(1, args.devices + 1):
        report_lng, report_lat = jitter(lng, lat, args.noise_m)
        status, body = call(
            "POST",
            f"{api}/reports",
            {
                "clientReportId": str(uuid.uuid4()),
                "deviceId": f"sim-{uuid.uuid4().hex[:12]}",
                "type": args.type,
                "confidence": round(random.uniform(0.55, 0.95), 2),
                "location": {"type": "Point", "coordinates": [report_lng, report_lat]},
                "accuracyM": round(random.uniform(3, 12), 1),
                "ts": datetime.now(UTC).isoformat(),
            },
        )
        if status >= 400:
            print(f"device {index}: HTTP {status} {body}")
            continue
        print(
            f"device {index}: HTTP {status} -> incident {body['incidentId']} "
            f"{body['incidentStatus']} ({body['distinctDevices']}/{body['requiredDevices']} devices)"
        )

    status, nearby = call("GET", f"{api}/incidents/nearby?lng={lng}&lat={lat}&radius=200")
    print(f"\nGET /incidents/nearby -> {len(nearby)} confirmed incident(s) within 200 m")
    for incident in nearby:
        print(f"  {incident['type']} {incident['status']} at {incident['distanceM']} m, "
              f"{incident['reportsCount']} reports, segment: {incident['segmentName']}")


if __name__ == "__main__":
    main()
