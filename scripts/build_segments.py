"""Build the road segments of the Huánuco – Tingo María corridor (seed data for the API).

* Geometry: route between both city centres from the public OSRM demo server
  (OpenStreetMap data, © OpenStreetMap contributors, ODbL), cut every SEGMENT_KM kilometres.
* District of each segment: Nominatim reverse geocoding of the segment midpoint (1 request/s).
* populationServed: INEI 2017 census population of that district (scripts/data/...json).
* isolationIndex: road distance from the segment midpoint to the nearest city with a hospital
  (Huánuco or Tingo María), divided by half the corridor length -> 0 (at a city) .. 1 (middle).

Output: services/api/seed/segments.geojson. Standard library only.

Usage:  python scripts/build_segments.py
"""

from __future__ import annotations

import json
import math
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "services" / "api" / "seed" / "segments.geojson"
POPULATION = Path(__file__).resolve().parent / "data" / "district_population_inei2017.json"
USER_AGENT = "viasegura-prototype/1.0 (road-safety hackathon; seed data build)"

HUANUCO = (-76.2397, -9.9294)  # Plaza de Armas (lng, lat)
TINGO_MARIA = (-75.9978, -9.2950)
SEGMENT_KM = 10.0
EARTH_RADIUS_M = 6_371_008.8


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed hosts
        return json.loads(response.read())


def haversine_m(a: list[float], b: list[float]) -> float:
    phi1, phi2 = math.radians(a[1]), math.radians(b[1])
    d_phi, d_lambda = math.radians(b[1] - a[1]), math.radians(b[0] - a[0])
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def interpolate(a: list[float], b: list[float], t: float) -> list[float]:
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def cut(line: list[list[float]], step_m: float) -> list[list[list[float]]]:
    """Cut a polyline into pieces of `step_m` metres (the last one may be shorter)."""
    pieces, current, walked = [], [line[0]], 0.0
    for a, b in zip(line, line[1:], strict=False):
        length = haversine_m(a, b)
        start = 0.0
        while walked + (length - start) >= step_m:
            t = (start + step_m - walked) / length
            point = interpolate(a, b, t)
            current.append(point)
            pieces.append(current)
            current, start, walked = [point], start + step_m - walked, 0.0
        walked += length - start
        current.append(b)
    if len(current) > 1 and walked > 200:
        pieces.append(current)
    elif pieces:
        pieces[-1].extend(current[1:])
    return pieces


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return stripped.lower().replace("-", " ").strip()


def district_of(lng: float, lat: float, known: dict[str, int]) -> str | None:
    query = urllib.parse.urlencode(
        {"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 12, "addressdetails": 1}
    )
    result = get_json(f"https://nominatim.openstreetmap.org/reverse?{query}")
    lookup = {normalize(name): name for name in known}
    for value in (result.get("address") or {}).values():
        if isinstance(value, str) and normalize(value) in lookup:
            return lookup[normalize(value)]
    return None


def main() -> None:
    population = {k: v for k, v in json.loads(POPULATION.read_text("utf-8")).items() if k[0] != "_"}
    coords = f"{HUANUCO[0]},{HUANUCO[1]};{TINGO_MARIA[0]},{TINGO_MARIA[1]}"
    route = get_json(
        f"https://router.project-osrm.org/route/v1/driving/{coords}"
        "?overview=full&geometries=geojson"
    )["routes"][0]
    line = route["geometry"]["coordinates"]
    total_km = route["distance"] / 1000
    print(f"Route Huánuco -> Tingo María: {total_km:.1f} km, {len(line)} points")

    features, km = [], 0.0
    pieces = cut(line, SEGMENT_KM * 1000)
    for index, piece in enumerate(pieces, start=1):
        length_km = sum(haversine_m(a, b) for a, b in zip(piece, piece[1:], strict=False)) / 1000
        km_start, km_end = km, km + length_km
        km = km_end
        middle_km = (km_start + km_end) / 2
        mid = piece[len(piece) // 2]
        district = district_of(mid[0], mid[1], population)
        time.sleep(1.1)  # Nominatim usage policy: max 1 request per second
        isolation = min(middle_km, total_km - middle_km) / (total_km / 2)
        name = f"Tramo {index:02d} · km {km_start:.0f}–{km_end:.0f}"
        if district:
            name += f" · {district}"
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[round(x, 6), round(y, 6)] for x, y in piece],
                },
                "properties": {
                    "code": f"HCO-TGM-{index:02d}",
                    "name": name,
                    "district": district,
                    "kmStart": round(km_start, 2),
                    "kmEnd": round(km_end, 2),
                    "populationServed": population.get(district, 0) if district else 0,
                    "isolationIndex": round(isolation, 3),
                    "trafficLevel": None,
                    "sources": {
                        "geometry": "OSRM route over OpenStreetMap (ODbL)",
                        "district": "Nominatim reverse geocoding (OpenStreetMap)",
                        "populationServed": "INEI Censo 2017, district total population",
                        "isolationIndex": "road km to nearest hospital city / half corridor length",
                        "trafficLevel": "not available (pending MTC/Provias traffic counts)",
                    },
                },
            }
        )
        print(f"  {name}: {length_km:.1f} km, isolation {isolation:.2f}, "
              f"population {features[-1]['properties']['populationServed']}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    collection = {
        "type": "FeatureCollection",
        "attribution": "© OpenStreetMap contributors (ODbL); population: INEI Censo 2017",
        "features": features,
    }
    OUTPUT.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(features)} segments to {OUTPUT}")


if __name__ == "__main__":
    main()
