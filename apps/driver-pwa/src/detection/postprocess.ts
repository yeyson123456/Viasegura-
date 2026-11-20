// Model output decoding. Mirrors services/api/app/services/detector.py so the phone and the
// server interpret the same ONNX model identically.

export type OutputLayout = "end2end" | "raw";

export interface ModelMeta {
  classes: string[];
  imgsz: number;
  input_name: string;
  output_name: string;
  output_layout: OutputLayout;
  sha256: string;
  size_mb?: number;
}

export interface Detection {
  label: string;
  classId: number;
  score: number;
  /** Normalized [x1, y1, x2, y2] in the source frame. */
  box: [number, number, number, number];
}

export interface Letterbox {
  scale: number;
  padX: number;
  padY: number;
  srcWidth: number;
  srcHeight: number;
}

type Row = [number, number, number, number, number, number]; // x1, y1, x2, y2, score, class

function iou(a: Row, b: Row): number {
  const x1 = Math.max(a[0], b[0]);
  const y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[2], b[2]);
  const y2 = Math.min(a[3], b[3]);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const areaA = (a[2] - a[0]) * (a[3] - a[1]);
  const areaB = (b[2] - b[0]) * (b[3] - b[1]);
  return inter / (areaA + areaB - inter + 1e-9);
}

/** Class-aware non-maximum suppression. */
export function nms(rows: Row[], threshold: number): Row[] {
  const sorted = [...rows].sort((a, b) => b[4] - a[4]);
  const kept: Row[] = [];
  for (const row of sorted) {
    if (kept.every((k) => k[5] !== row[5] || iou(k, row) <= threshold)) kept.push(row);
  }
  return kept;
}

/** Decode the raw output tensor into rows in letterboxed pixels. */
export function decode(
  data: Float32Array,
  dims: readonly number[],
  layout: OutputLayout,
  minScore: number,
  iouThreshold = 0.5,
): Row[] {
  if (layout === "end2end") {
    // dims = [1, maxDet, 6]
    const rows: Row[] = [];
    for (let i = 0; i < dims[1]; i++) {
      const o = i * 6;
      if (data[o + 4] >= minScore) {
        rows.push([data[o], data[o + 1], data[o + 2], data[o + 3], data[o + 4], data[o + 5]]);
      }
    }
    return rows;
  }
  // raw: dims = [1, 4 + classes, anchors], channel-major
  const channels = dims[1];
  const anchors = dims[2];
  const rows: Row[] = [];
  for (let a = 0; a < anchors; a++) {
    let best = 0;
    let cls = -1;
    for (let c = 4; c < channels; c++) {
      const score = data[c * anchors + a];
      if (score > best) {
        best = score;
        cls = c - 4;
      }
    }
    if (best < minScore) continue;
    const cx = data[a];
    const cy = data[anchors + a];
    const w = data[2 * anchors + a];
    const h = data[3 * anchors + a];
    rows.push([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, best, cls]);
  }
  return nms(rows, iouThreshold);
}

/** Map letterboxed rows back to normalized boxes in the source frame. */
export function toDetections(rows: Row[], lb: Letterbox, classes: string[]): Detection[] {
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  return rows.map((r) => ({
    label: classes[r[5]] ?? `class_${r[5]}`,
    classId: r[5],
    score: r[4],
    box: [
      clamp((r[0] - lb.padX) / lb.scale / lb.srcWidth),
      clamp((r[1] - lb.padY) / lb.scale / lb.srcHeight),
      clamp((r[2] - lb.padX) / lb.scale / lb.srcWidth),
      clamp((r[3] - lb.padY) / lb.scale / lb.srcHeight),
    ],
  }));
}

/** Letterbox geometry for a source frame (same rounding as the server). */
export function letterbox(srcWidth: number, srcHeight: number, size: number): Letterbox {
  const scale = Math.min(size / srcWidth, size / srcHeight);
  const newW = Math.round(srcWidth * scale);
  const newH = Math.round(srcHeight * scale);
  return { scale, padX: Math.floor((size - newW) / 2), padY: Math.floor((size - newH) / 2), srcWidth, srcHeight };
}

/** RGBA pixels (size x size) -> CHW float32 in [0, 1]. */
export function toCHW(rgba: Uint8ClampedArray, size: number): Float32Array {
  const plane = size * size;
  const out = new Float32Array(3 * plane);
  for (let i = 0, p = 0; p < plane; i += 4, p++) {
    out[p] = rgba[i] / 255;
    out[plane + p] = rgba[i + 1] / 255;
    out[2 * plane + p] = rgba[i + 2] / 255;
  }
  return out;
}
