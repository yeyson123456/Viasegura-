"""Generate static PWA assets: PNG icons and the corridor polyline used by the simulated drive.

Usage (any Python with Pillow, e.g. the API venv):
    python scripts/make_pwa_assets.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "apps" / "driver-pwa" / "public"
SEED = ROOT / "services" / "api" / "seed" / "segments.geojson"


def icon(size: int) -> Image.Image:
    """Same design as public/icons/icon.svg: preventive-sign diamond with a road, navy tile."""
    scale = size / 512
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def s(points):
        return [(x * scale, y * scale) for x, y in points]

    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=96 * scale, fill="#0b1f36")
    diamond = s([(256, 58), (454, 256), (256, 454), (58, 256)])
    draw.polygon(diamond, fill="#f2b705", outline="#111111", width=max(2, round(18 * scale)))
    draw.polygon(s([(226, 372), (246, 160), (266, 160), (286, 372)]), fill="#111111")
    for top, bottom in ((182, 216), (240, 280), (304, 348)):
        draw.rectangle(s([(251, top), (261, bottom)]), fill="#f2b705")
    return image


def main() -> None:
    (PUBLIC / "icons").mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        icon(size).save(PUBLIC / "icons" / f"icon-{size}.png")

    features = json.loads(SEED.read_text(encoding="utf-8"))["features"]
    features.sort(key=lambda f: f["properties"]["kmStart"])
    coordinates: list[list[float]] = []
    for feature in features:
        line = feature["geometry"]["coordinates"]
        coordinates.extend(line if not coordinates else line[1:])
    # Keep roughly one point every ~3 vertices: plenty for a simulated drive, small file.
    simplified = coordinates[::3] + [coordinates[-1]]
    (PUBLIC / "data").mkdir(parents=True, exist_ok=True)
    (PUBLIC / "data" / "corridor.json").write_text(
        json.dumps({"name": "Huánuco – Tingo María", "attribution": "© OpenStreetMap contributors",
                    "coordinates": simplified}),
        encoding="utf-8",
    )
    print(f"icons: 192, 512 px | corridor: {len(simplified)} points")


if __name__ == "__main__":
    main()
