"""Build the PWA demo video from HELD-OUT test images (never seen in training).

Pothole frames come from the RDD2022 test split, obstacle frames from the TerrainSense test
videos (clip2, road1). Each frame is shown for --seconds, letterboxed to 1280x720, and the
result is written as WebM (VP8), which every modern browser plays.

Usage (from ml/):
    python make_demo_video.py                        # -> apps/driver-pwa/public/demo/demo-road.webm
    python make_demo_video.py --frames 30 --seconds 1.5
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import cv2
import numpy as np

ML_DIR = Path(__file__).resolve().parent
DATASET = ML_DIR / "data" / "viasegura"
OUTPUT = ML_DIR.parent / "apps" / "driver-pwa" / "public" / "demo" / "demo-road.webm"
WIDTH, HEIGHT, FPS = 1280, 720, 15


def letterbox(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    scale = min(WIDTH / w, HEIGHT / h)
    resized = cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    y, x = (HEIGHT - resized.shape[0]) // 2, (WIDTH - resized.shape[1]) // 2
    canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=int, default=36, help="number of still images")
    parser.add_argument("--seconds", type=float, default=1.6, help="time each image stays on screen")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rows = list(csv.DictReader(open(DATASET / "manifest.csv", encoding="utf-8")))
    test = [r for r in rows if r["split"] == "test"]

    def labelled_area(row: dict, class_id: int) -> float:
        """Total area of the GROUND-TRUTH boxes of one class (selection never uses the model)."""
        label = DATASET / "labels" / "test" / (Path(row["file"]).stem + ".txt")
        total = 0.0
        for line in label.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 5 and int(parts[0]) == class_id:
                total += float(parts[3]) * float(parts[4])
        return total

    # Clear examples: road (dash-cam) images with the largest labelled potholes, and obstacle
    # frames from the TerrainSense road video only.
    potholes = sorted(
        (r for r in test if r["source"] == "rdd2022" and int(r["n_pothole"]) >= 1),
        key=lambda r: labelled_area(r, 0),
        reverse=True,
    )
    obstacles = sorted(
        (r for r in test if r["source"] == "terrainsense" and r["group"] == "road1" and int(r["n_obstacle"]) >= 1),
        key=lambda r: labelled_area(r, 1),
        reverse=True,
    )
    rng = random.Random(args.seed)
    half = args.frames // 2
    chosen = potholes[:half] + obstacles[: args.frames - half]
    rng.shuffle(chosen)
    print(f"selected {min(half, len(potholes))} pothole + {min(args.frames - half, len(obstacles))} obstacle frames")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(OUTPUT), cv2.VideoWriter_fourcc(*"VP80"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise SystemExit("OpenCV cannot write VP8/WebM on this machine")
    repeats = max(1, round(args.seconds * FPS))
    for row in chosen:
        frame = cv2.imread(str(DATASET / "images" / "test" / row["file"]))
        if frame is None:
            continue
        frame = letterbox(frame)
        for _ in range(repeats):
            writer.write(frame)
    writer.release()
    size_mb = OUTPUT.stat().st_size / 1e6
    print(f"Wrote {OUTPUT} ({len(chosen)} test images, {len(chosen) * args.seconds:.0f} s, {size_mb:.1f} MB)")
    (OUTPUT.parent / "CREDITS.txt").write_text(
        "demo-road.webm is assembled from held-out test images of:\n"
        "- RDD2022 (Arya et al., CC BY 4.0) https://doi.org/10.6084/m9.figshare.21431547\n"
        "- TerrainSense (Bhute, Rane, Joshi, CC BY 4.0) https://doi.org/10.17632/r6cmjrr6kv.3\n"
        "Built by ml/make_demo_video.py.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
