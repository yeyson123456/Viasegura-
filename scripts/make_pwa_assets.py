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
    """Same design as public/icons/icon.svg: road + warning triangle on a dark tile."""
    scale = size / 512
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def s(points):
        return [(x * scale, y * scale) for x, y in points]

    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=112 * scale, fill="#0b1220")
    draw.polygon(s([(196, 448), (236, 96), (276, 96), (316, 448)]), fill="#2c3b5c")
    for top, bottom, half_top, half_bottom in ((140, 192, 4, 7), (236, 308, 8, 12), (352, 448, 14, 19)):
        draw.polygon(
            s([(256 - half_top, top), (256 + half_top, top), (256 + half_bottom, bottom),
               (256 - half_bottom, bottom)]),
            fill="#f3f6fb",
        )
    draw.polygon(s([(256, 64), (400, 316), (112, 316)]), fill="#ffb020", outline="#0b1220",
                 width=max(1, round(14 * scale)))
    draw.rounded_rectangle(s([(244, 148), (268, 244)]), radius=12 * scale, fill="#0b1220")
    draw.ellipse(s([(241, 265), (271, 295)]), fill="#0b1220")
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
