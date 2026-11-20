"""Evaluate the detector on the held-out test split: precision, recall and mAP per class.

By default it evaluates the deployed artifact (ml/models/hazards.onnx) at the resolution recorded
in hazards.json, so the numbers describe exactly the model that runs on the phone and in the API.
Results are printed and saved to ml/results/.

Usage (from ml/):
    python evaluate.py                         # deployed ONNX model, test split
    python evaluate.py --by-source             # also one evaluation per data source
    python evaluate.py --model runs/yolo26n-640/weights/best.pt --split val
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import ultralytics
import yaml
from ultralytics import YOLO

ML_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = ML_DIR / "data" / "viasegura" / "dataset.yaml"
RESULTS_DIR = ML_DIR / "results"


def label_counts(dataset_dir: Path, split: str, files: list[str] | None, n_classes: int):
    """Images and boxes per class straight from the label files (independent of the validator)."""
    label_dir = dataset_dir / "labels" / split
    stems = [Path(f).stem for f in files] if files else [p.stem for p in label_dir.glob("*.txt")]
    images, instances, images_with = 0, Counter(), Counter()
    for stem in stems:
        images += 1
        path = label_dir / f"{stem}.txt"
        classes = [int(line.split()[0]) for line in path.read_text().splitlines() if line.strip()]
        instances.update(classes)
        images_with.update(set(classes))
    return images, {c: instances[c] for c in range(n_classes)}, images_with


def evaluate(model_path: Path, data: Path, split: str, imgsz: int, device: str, args, tag: str):
    model = YOLO(str(model_path), task="detect")
    is_onnx = model_path.suffix == ".onnx"
    metrics = model.val(
        data=str(data),
        split=split,
        imgsz=imgsz,
        batch=1 if is_onnx else 16,
        conf=args.conf,
        iou=args.iou,
        device=device,
        plots=True,
        project=str(ML_DIR / "runs" / "eval"),
        name=tag,
        exist_ok=True,
        verbose=False,
    )
    box = metrics.box
    results = {
        "all": {
            "precision": float(box.mp),
            "recall": float(box.mr),
            "mAP50": float(box.map50),
            "mAP50-95": float(box.map),
        }
    }
    for index, class_index in enumerate(box.ap_class_index):
        precision, recall, ap50, ap = box.class_result(index)
        results[model.names[int(class_index)]] = {
            "precision": float(precision),
            "recall": float(recall),
            "mAP50": float(ap50),
            "mAP50-95": float(ap),
        }
    return results, {k: round(float(v), 2) for k, v in metrics.speed.items()}


def print_table(title: str, results: dict, images: int, instances: dict, names: dict) -> None:
    print(f"\n{title}")
    header = f"{'class':<10} {'images':>7} {'boxes':>7} {'P':>7} {'R':>7} {'mAP50':>7} {'mAP50-95':>9}"
    print(header + "\n" + "-" * len(header))
    for name, values in results.items():
        boxes = sum(instances.values()) if name == "all" else instances.get(names.get(name, -1), 0)
        print(
            f"{name:<10} {images:>7} {boxes:>7} {values['precision']:>7.3f} {values['recall']:>7.3f}"
            f" {values['mAP50']:>7.3f} {values['mAP50-95']:>9.3f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=str(ML_DIR / "models" / "hazards.onnx"))
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--imgsz", type=int, default=None, help="default: hazards.json or 640")
    parser.add_argument("--device", default=None, help="default: cpu for ONNX, 0 for .pt")
    parser.add_argument("--conf", type=float, default=0.001, help="standard for mAP")
    parser.add_argument("--iou", type=float, default=0.7)
    parser.add_argument("--by-source", action="store_true", help="also evaluate each data source")
    args = parser.parse_args()

    model_path = Path(args.model).resolve()
    if not model_path.exists():
        raise SystemExit(f"{model_path} not found; train and export first")
    meta_path = model_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    imgsz = args.imgsz or meta.get("imgsz", 640)
    device = args.device or ("cpu" if model_path.suffix == ".onnx" else "0")
    data = Path(args.data).resolve()
    dataset = yaml.safe_load(data.read_text(encoding="utf-8"))
    dataset_dir = Path(dataset["path"])
    names = {name: index for index, name in dataset["names"].items()}
    n_classes = len(names)

    runs = {"overall": (data, None)}
    if args.by_source:
        by_source: dict[str, list[str]] = defaultdict(list)
        with open(dataset_dir / "manifest.csv", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["split"] == args.split:
                    by_source[row["source"]].append(row["file"])
        for source, files in sorted(by_source.items()):
            list_file = dataset_dir / f"{args.split}_{source}.txt"
            list_file.write_text(
                "\n".join(str(dataset_dir / "images" / args.split / f) for f in files), "utf-8"
            )
            subset = {**dataset, args.split: str(list_file)}
            subset_yaml = dataset_dir / f"dataset_{args.split}_{source}.yaml"
            subset_yaml.write_text(yaml.safe_dump(subset, sort_keys=False), encoding="utf-8")
            runs[source] = (subset_yaml, files)

    report = {
        "model": str(model_path.relative_to(ML_DIR)) if model_path.is_relative_to(ML_DIR) else str(
            model_path
        ),
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "imgsz": imgsz,
        "split": args.split,
        "conf": args.conf,
        "iou": args.iou,
        "device": device,
        "note": "Precision/recall at the F1-optimal confidence (Ultralytics convention).",
        "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "ultralytics_version": ultralytics.__version__,
        "subsets": {},
    }
    for tag, (subset_yaml, files) in runs.items():
        images, instances, _ = label_counts(dataset_dir, args.split, files, n_classes)
        results, speed = evaluate(model_path, subset_yaml, args.split, imgsz, device, args, tag)
        print_table(f"[{tag}] {args.split} split, {model_path.name} @ {imgsz}px", results,
                    images, instances, names)
        report["subsets"][tag] = {
            "images": images,
            "instances": {name: instances[index] for name, index in names.items()},
            "metrics": results,
            "speed_ms_per_image": speed,
        }

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"eval_{model_path.stem}_{args.split}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
