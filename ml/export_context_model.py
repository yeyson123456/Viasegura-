"""Export the COCO-pretrained YOLO26n as a *context* model for the phone.

The hazard model only knows `pothole` and `obstacle`. The context model recognises people and
vehicles so the app can (1) discard "obstacle" detections that are really a person or a vehicle
and (2) blur people and vehicles in uploaded photos (faces, licence plates).

Usage (from ml/):  python export_context_model.py [--imgsz 416]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from ultralytics import YOLO

ML_DIR = Path(__file__).resolve().parent
PWA_MODELS_DIR = ML_DIR.parent / "apps" / "driver-pwa" / "public" / "models"
CONTEXT_CLASSES = ["person", "bicycle", "car", "motorcycle", "bus", "truck"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weights", default="yolo26n.pt", help="COCO-pretrained checkpoint")
    parser.add_argument("--imgsz", type=int, default=416, help="people/vehicles are large; 416 is enough")
    args = parser.parse_args()

    model = YOLO(args.weights)
    exported = Path(model.export(format="onnx", imgsz=args.imgsz, opset=17, simplify=True, nms=False))
    target = ML_DIR / "models" / "context.onnx"
    target.parent.mkdir(exist_ok=True)
    shutil.copy2(exported, target)
    names = [model.names[i] for i in sorted(model.names)]
    metadata = {
        "name": "coco-context",
        "classes": names,
        "context_classes": CONTEXT_CLASSES,
        "imgsz": args.imgsz,
        "input_name": "images",
        "output_name": "output0",
        "output_layout": "end2end",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "size_mb": round(target.stat().st_size / 1e6, 2),
        "source_weights": f"{args.weights} (Ultralytics, COCO-pretrained)",
    }
    (target.with_suffix(".json")).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    PWA_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("context.onnx", "context.json"):
        shutil.copy2(ML_DIR / "models" / name, PWA_MODELS_DIR / name)
    print(json.dumps({k: v for k, v in metadata.items() if k != "classes"}, indent=2))


if __name__ == "__main__":
    main()
