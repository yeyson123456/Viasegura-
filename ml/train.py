"""Train the two-class road-hazard detector (pothole, obstacle) with Ultralytics YOLO (nano).

Usage (from ml/):
    python train.py                         # YOLO26n, 640 px, settings below
    python train.py --model yolo11n.pt      # fallback architecture
    python train.py --epochs 5 --fraction 0.1  # quick smoke run
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ultralytics import YOLO

ML_DIR = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=str(ML_DIR / "data" / "viasegura" / "dataset.yaml"))
    parser.add_argument("--model", default="yolo26n.pt", help="yolo26n.pt (default) or yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16, help="16 fits a 4 GB GPU at 640 px")
    parser.add_argument("--device", default="0", help="'0' for the first GPU, 'cpu' otherwise")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--fraction", type=float, default=1.0, help="share of train set to use")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--name", default=None, help="run name under ml/runs/")
    parser.add_argument(
        "--resume",
        default=None,
        help="path to an interrupted run's last.pt; continues with that run's settings",
    )
    args = parser.parse_args()

    if args.resume:
        started = time.time()
        model = YOLO(args.resume)
        model.train(resume=True)
        print(f"resumed run finished in {(time.time() - started) / 60:.1f} min: {model.trainer.save_dir}")
        return

    name = args.name or f"{Path(args.model).stem}-{args.imgsz}"
    model = YOLO(args.model)  # downloads the COCO-pretrained nano checkpoint if missing
    started = time.time()
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        patience=args.patience,
        fraction=args.fraction,
        seed=args.seed,
        deterministic=True,
        project=str(ML_DIR / "runs"),
        name=name,
        exist_ok=False,
        # Road scenes: horizontal flips are realistic, vertical flips are not.
        fliplr=0.5,
        flipud=0.0,
        close_mosaic=5,
        plots=True,
    )
    save_dir = Path(model.trainer.save_dir)
    summary = {
        "run": save_dir.name,
        "model": args.model,
        "imgsz": args.imgsz,
        "epochs_requested": args.epochs,
        "train_minutes": round((time.time() - started) / 60, 1),
        "best_weights": str(save_dir / "weights" / "best.pt"),
    }
    (save_dir / "train_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
