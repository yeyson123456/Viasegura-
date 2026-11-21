"""Add close-up pothole photos (the kind of picture someone shows to the camera) as a local source.

RDD2022 potholes are small and far away (dash-cam). These public Roboflow exports on Hugging Face
show potholes from close range:
  * Ryukijano/Pothole-detection-Yolov8 (YOLO format, OpenRAIL)
  * keremberke/pothole-segmentation (COCO format, CC BY 4.0)
Both are written to ml/data/local/pothole_closeup/{images,labels} with class 0 = pothole, which
configs/sources.yaml uses as the `pothole_closeup` local source.

Usage (from ml/):  python add_closeup_potholes.py && python prepare_dataset.py --skip-download
"""

from __future__ import annotations

import io
import json
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
OUT = ML_DIR / "data" / "local" / "pothole_closeup"
HF = "https://huggingface.co"
UA = {"User-Agent": "viasegura-dataset-prep/1.0"}


def get(url: str, retries: int = 5) -> bytes:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:  # noqa: S310
                return r.read()
        except Exception:  # noqa: BLE001 - retry transient network errors
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def ryukijano() -> int:
    repo = "Ryukijano/Pothole-detection-Yolov8"
    files = [s["rfilename"] for s in json.loads(get(f"{HF}/api/datasets/{repo}"))["siblings"]]
    names = json.dumps(get(f"{HF}/datasets/{repo}/resolve/main/data.yaml").decode())
    print(f"{repo}: data.yaml -> {names[:120]}")
    images = [f for f in files if "/images/" in f and f.lower().endswith((".jpg", ".jpeg", ".png"))]

    def fetch(path: str) -> bool:
        stem = Path(path).stem
        label_path = path.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt"
        if label_path not in files:
            return False
        lines = []
        for line in get(f"{HF}/datasets/{repo}/resolve/main/{label_path}").decode().splitlines():
            parts = line.split()
            if len(parts) == 5:  # single-class dataset: any class id -> pothole (0)
                lines.append("0 " + " ".join(parts[1:]))
        (OUT / "labels" / f"ryu_{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (OUT / "images" / f"ryu_{stem}.jpg").write_bytes(get(f"{HF}/datasets/{repo}/resolve/main/{path}"))
        return True

    with ThreadPoolExecutor(12) as pool:
        return sum(pool.map(fetch, images))


def keremberke() -> int:
    repo = "keremberke/pothole-segmentation"
    count = 0
    for split in ("train", "valid", "test"):
        archive = zipfile.ZipFile(io.BytesIO(get(f"{HF}/datasets/{repo}/resolve/main/data/{split}.zip")))
        coco_name = next(n for n in archive.namelist() if n.endswith(".json"))
        coco = json.loads(archive.read(coco_name))
        boxes: dict[int, list] = {}
        for ann in coco["annotations"]:
            boxes.setdefault(ann["image_id"], []).append(ann["bbox"])
        for image in coco["images"]:
            member = next((n for n in archive.namelist() if n.endswith(image["file_name"])), None)
            if member is None:
                continue
            w, h = image["width"], image["height"]
            lines = [
                f"0 {(x + bw / 2) / w:.6f} {(y + bh / 2) / h:.6f} {bw / w:.6f} {bh / h:.6f}"
                for x, y, bw, bh in boxes.get(image["id"], [])
                if bw > 1 and bh > 1
            ]
            stem = f"ker_{split}_{Path(image['file_name']).stem}"
            (OUT / "images" / f"{stem}.jpg").write_bytes(archive.read(member))
            (OUT / "labels" / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            count += 1
    return count


def main() -> None:
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    (OUT / "labels").mkdir(parents=True, exist_ok=True)
    print(f"Ryukijano images: {ryukijano()}")
    print(f"keremberke images: {keremberke()}")
    total = len(list((OUT / "images").glob("*.jpg")))
    print(f"close-up pothole images ready: {total} in {OUT}")


if __name__ == "__main__":
    main()
