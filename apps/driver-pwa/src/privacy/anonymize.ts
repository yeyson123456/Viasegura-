// Privacy filter applied ON THE PHONE before any photo leaves it.
//
// 1. Only a crop around the hazard is kept (never the full frame), at most 480 px.
// 2. Everything outside the hazard box is pixelated with large blocks.
// 3. The hazard box itself is rendered from a copy of at most 160 px, enough to see a pothole or
//    rocks but far too coarse for a face or a licence plate to be legible.
// 4. Re-encoding through a canvas produces a JPEG without EXIF/GPS metadata.
// The server re-encodes again and scripts/privacy_audit.py checks stored photos.

export type Box = [number, number, number, number]; // normalized x1, y1, x2, y2

export const PRIVACY = {
  maxSide: 480,
  hazardMaxSide: 160,
  expand: 0.6, // context added around the hazard box, relative to its size
  minCropShare: 0.35, // crop covers at least this share of the frame in each dimension
  pixelBlocks: 24, // context is reduced to ~24 blocks across
  quality: 0.8,
};

export interface CropPlan {
  crop: { x: number; y: number; w: number; h: number }; // source pixels
  out: { w: number; h: number }; // output pixels
  hazard: { x: number; y: number; w: number; h: number }; // in output pixels
}

/** Pure geometry (unit-tested): which region to keep and how large the output is. */
export function planCrop(box: Box, frameW: number, frameH: number): CropPlan {
  const [x1, y1, x2, y2] = [box[0] * frameW, box[1] * frameH, box[2] * frameW, box[3] * frameH];
  const bw = Math.max(1, x2 - x1);
  const bh = Math.max(1, y2 - y1);
  const w = Math.min(frameW, Math.max(bw * (1 + 2 * PRIVACY.expand), frameW * PRIVACY.minCropShare));
  const h = Math.min(frameH, Math.max(bh * (1 + 2 * PRIVACY.expand), frameH * PRIVACY.minCropShare));
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2;
  const x = Math.min(Math.max(0, cx - w / 2), frameW - w);
  const y = Math.min(Math.max(0, cy - h / 2), frameH - h);
  const scale = Math.min(1, PRIVACY.maxSide / Math.max(w, h));
  return {
    crop: { x, y, w, h },
    out: { w: Math.max(1, Math.round(w * scale)), h: Math.max(1, Math.round(h * scale)) },
    hazard: { x: (x1 - x) * scale, y: (y1 - y) * scale, w: bw * scale, h: bh * scale },
  };
}

/** Runs in the detection worker (OffscreenCanvas); returns a metadata-free JPEG. */
export async function anonymize(frame: ImageBitmap, box: Box): Promise<Blob> {
  const plan = planCrop(box, frame.width, frame.height);
  const { crop, out, hazard } = plan;
  const canvas = new OffscreenCanvas(out.w, out.h);
  const ctx = canvas.getContext("2d") as OffscreenCanvasRenderingContext2D;

  // Context: pixelate by drawing into a tiny canvas and scaling it up without smoothing.
  const blocksW = Math.max(4, Math.round(PRIVACY.pixelBlocks));
  const blocksH = Math.max(3, Math.round((blocksW * out.h) / out.w));
  const tiny = new OffscreenCanvas(blocksW, blocksH);
  const tinyCtx = tiny.getContext("2d") as OffscreenCanvasRenderingContext2D;
  tinyCtx.drawImage(frame, crop.x, crop.y, crop.w, crop.h, 0, 0, blocksW, blocksH);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(tiny, 0, 0, out.w, out.h);

  // Hazard: low-resolution copy (<= hazardMaxSide px) upscaled smoothly into its box.
  const hScale = Math.min(1, PRIVACY.hazardMaxSide / Math.max(hazard.w, hazard.h));
  const lowW = Math.max(1, Math.round(hazard.w * hScale));
  const lowH = Math.max(1, Math.round(hazard.h * hScale));
  const low = new OffscreenCanvas(lowW, lowH);
  const lowCtx = low.getContext("2d") as OffscreenCanvasRenderingContext2D;
  const srcX = crop.x + hazard.x / (out.w / crop.w);
  const srcY = crop.y + hazard.y / (out.h / crop.h);
  const srcW = hazard.w / (out.w / crop.w);
  const srcH = hazard.h / (out.h / crop.h);
  lowCtx.drawImage(frame, srcX, srcY, srcW, srcH, 0, 0, lowW, lowH);
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(low, hazard.x, hazard.y, hazard.w, hazard.h);

  return canvas.convertToBlob({ type: "image/jpeg", quality: PRIVACY.quality });
}
