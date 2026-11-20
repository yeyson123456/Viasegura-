"""Server-side re-detection with the same ONNX model that runs on the phone."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

logger = logging.getLogger("viasegura.detector")


@dataclass(frozen=True)
class Detection:
    type: str
    confidence: float
    box: tuple[float, float, float, float]  # normalized x1, y1, x2, y2


def letterbox(image: Image.Image, size: int) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Resize keeping aspect ratio and pad to size x size (value 114), as Ultralytics does."""
    width, height = image.size
    scale = min(size / width, size / height)
    new_w, new_h = round(width * scale), round(height * scale)
    canvas = Image.new("RGB", (size, size), (114, 114, 114))
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas.paste(image.resize((new_w, new_h), Image.Resampling.BILINEAR), (pad_x, pad_y))
    tensor = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return tensor, scale, (pad_x, pad_y)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep: list[int] = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        best = int(order[0])
        keep.append(best)
        rest = order[1:]
        x1 = np.maximum(boxes[best, 0], boxes[rest, 0])
        y1 = np.maximum(boxes[best, 1], boxes[rest, 1])
        x2 = np.minimum(boxes[best, 2], boxes[rest, 2])
        y2 = np.minimum(boxes[best, 3], boxes[rest, 3])
        inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        iou = inter / (areas[best] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_threshold]
    return keep


def decode(output: np.ndarray, layout: str, min_confidence: float, iou: float = 0.5) -> np.ndarray:
    """Model output -> rows [x1, y1, x2, y2, score, class] in letterboxed pixels."""
    if layout == "end2end":  # (1, max_det, 6), already NMS-free
        rows = output[0]
        return rows[rows[:, 4] >= min_confidence]
    predictions = output[0].T  # raw: (1, 4 + classes, anchors) -> (anchors, 4 + classes)
    scores = predictions[:, 4:]
    classes, confidence = scores.argmax(axis=1), scores.max(axis=1)
    mask = confidence >= min_confidence
    predictions, classes, confidence = predictions[mask], classes[mask], confidence[mask]
    centers, sizes = predictions[:, :2], predictions[:, 2:4]
    boxes = np.concatenate([centers - sizes / 2, centers + sizes / 2], axis=1)
    # Class-aware NMS: shift each class to its own coordinate range.
    keep = nms(boxes + classes[:, None] * 10_000.0, confidence, iou)
    return np.concatenate(
        [boxes[keep], confidence[keep, None], classes[keep, None].astype(np.float32)], axis=1
    )


class HazardDetector:
    def __init__(self, model_path: Path) -> None:
        metadata = json.loads(model_path.with_suffix(".json").read_text(encoding="utf-8"))
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.imgsz = int(metadata["imgsz"])
        self.classes: list[str] = metadata["classes"]
        self.layout: str = metadata["output_layout"]
        self.version: str = metadata.get("sha256", "")[:12]

    @classmethod
    def load(cls, path: str) -> HazardDetector | None:
        model_path = Path(path)
        if not (model_path.exists() and model_path.with_suffix(".json").exists()):
            logger.warning("detector_disabled", extra={"model_path": str(model_path)})
            return None
        detector = cls(model_path)
        logger.info("detector_loaded", extra={"model_version": detector.version})
        return detector

    def detect(self, image: Image.Image, min_confidence: float) -> list[Detection]:
        tensor, scale, (pad_x, pad_y) = letterbox(image, self.imgsz)
        output = self.session.run(None, {self.input_name: tensor})[0]
        width, height = image.size
        detections = []
        for x1, y1, x2, y2, score, class_id in decode(output, self.layout, min_confidence):
            box = (
                (x1 - pad_x) / scale / width,
                (y1 - pad_y) / scale / height,
                (x2 - pad_x) / scale / width,
                (y2 - pad_y) / scale / height,
            )
            clipped = tuple(min(1.0, max(0.0, float(value))) for value in box)
            detections.append(Detection(self.classes[int(class_id)], float(score), clipped))
        return detections
