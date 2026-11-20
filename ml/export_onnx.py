"""Export trained weights to ONNX for the phone (ONNX Runtime Web) and the API (onnxruntime).

Writes ml/models/hazards.onnx plus hazards.json (metadata read by the PWA and the API) and copies
both into apps/driver-pwa/public/models/.

Usage (from ml/):
    python export_onnx.py                                   # newest ml/runs/*/weights/best.pt
    python export_onnx.py --weights runs/yolo26n-640/weights/best.pt --imgsz 640
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import onnxruntime as ort
import ultralytics
from ultralytics import YOLO

ML_DIR = Path(__file__).resolve().parent
REPO_DIR = ML_DIR.parent
MODELS_DIR = ML_DIR / "models"
PWA_MODELS_DIR = REPO_DIR / "apps" / "driver-pwa" / "public" / "models"


def newest_best() -> Path:
    candidates = sorted(
        (ML_DIR / "runs").glob("*/weights/best.pt"), key=lambda path: path.stat().st_mtime
    )
    if not candidates:
        raise SystemExit("no trained weights under ml/runs/; run train.py first")
    return candidates[-1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weights", default=None)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--opset", type=int, default=17, help="17 is safe for ONNX Runtime Web")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="export the one-to-many head (needs NMS) instead of YOLO26's NMS-free end-to-end head",
    )
    args = parser.parse_args()

    weights = Path(args.weights).resolve() if args.weights else newest_best()
    model = YOLO(str(weights))
    names = model.names
    # Ultralytics: nms=False selects the end-to-end (NMS-free) branch; nms=None exports raw boxes.
    exported = Path(
        model.export(
            format="onnx",
            imgsz=args.imgsz,
            opset=args.opset,
            simplify=True,
            dynamic=False,
            nms=None if args.raw else False,
        )
    )

    # Inspect the real output layout instead of assuming it.
    session = ort.InferenceSession(str(exported), providers=["CPUExecutionProvider"])
    model_input, model_output = session.get_inputs()[0], session.get_outputs()[0]
    output = session.run(None, {model_input.name: np.zeros(model_input.shape, np.float32)})[0]
    if output.ndim == 3 and output.shape[2] == 6:
        layout = "end2end"  # [x1, y1, x2, y2, score, class] per row, already NMS-free
    elif output.ndim == 3 and output.shape[1] == 4 + len(names):
        layout = "raw"  # [cx, cy, w, h, score_0..score_n] per anchor column; needs NMS
    else:
        raise SystemExit(f"unexpected output shape {output.shape}")

    MODELS_DIR.mkdir(exist_ok=True)
    target = MODELS_DIR / "hazards.onnx"
    shutil.copy2(exported, target)
    try:
        source = str(weights.relative_to(ML_DIR))
    except ValueError:
        source = weights.name
    metadata = {
        "name": "viasegura-hazards",
        "classes": [names[index] for index in sorted(names)],
        "imgsz": args.imgsz,
        "input_name": model_input.name,
        "input_shape": list(model_input.shape),
        "output_name": model_output.name,
        "output_shape": list(output.shape),
        "output_layout": layout,
        "boxes_in": "letterboxed input pixels",
        "letterbox_value": 114,
        "opset": args.opset,
        "source_weights": source.replace("\\", "/"),
        "sha256": sha256(target),
        "size_mb": round(target.stat().st_size / 1e6, 2),
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "ultralytics_version": ultralytics.__version__,
    }
    (MODELS_DIR / "hazards.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    PWA_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("hazards.onnx", "hazards.json"):
        shutil.copy2(MODELS_DIR / name, PWA_MODELS_DIR / name)
    print(json.dumps(metadata, indent=2))
    print(f"\nWrote {target} and copied it to {PWA_MODELS_DIR}")


if __name__ == "__main__":
    main()
