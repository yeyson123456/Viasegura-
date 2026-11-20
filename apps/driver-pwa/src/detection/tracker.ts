// Temporal confirmation on the phone: a hazard is reported only when the same class is seen in
// K of the last M analysed frames, and not again while the car is still near the last report.
import { haversineM, type LngLat } from "../lib/geo";
import type { Detection } from "./postprocess";

export interface TrackerOptions {
  windowFrames: number; // M
  hitsRequired: number; // K
  minScore: number;
  minScoreByLabel?: Record<string, number>; // stricter floors per class (e.g. obstacle)
  cooldownMeters: number;
  cooldownMs: number;
}

interface LastReport {
  at: number;
  position: LngLat | null;
}

export class HazardTracker {
  private history = new Map<string, number[]>(); // label -> best score per frame (0 = absent)
  private lastReport = new Map<string, LastReport>();

  constructor(private readonly options: TrackerOptions) {}

  /** Feed one frame; returns the detections that should become reports now. */
  update(detections: Detection[], now: number, position: LngLat | null): Detection[] {
    const best = new Map<string, Detection>();
    for (const d of detections) {
      const floor = Math.max(this.options.minScore, this.options.minScoreByLabel?.[d.label] ?? 0);
      if (d.score < floor) continue;
      const current = best.get(d.label);
      if (!current || d.score > current.score) best.set(d.label, d);
    }
    const labels = new Set([...this.history.keys(), ...best.keys()]);
    const confirmed: Detection[] = [];
    for (const label of labels) {
      const frames = this.history.get(label) ?? [];
      frames.push(best.get(label)?.score ?? 0);
      while (frames.length > this.options.windowFrames) frames.shift();
      this.history.set(label, frames);
      const hits = frames.filter((score) => score > 0).length;
      const detection = best.get(label);
      if (detection && hits >= this.options.hitsRequired && !this.coolingDown(label, now, position)) {
        this.lastReport.set(label, { at: now, position });
        confirmed.push(detection);
      }
    }
    return confirmed;
  }

  private coolingDown(label: string, now: number, position: LngLat | null): boolean {
    const last = this.lastReport.get(label);
    if (!last) return false;
    if (now - last.at < this.options.cooldownMs) return true;
    // Still close to where this hazard type was last reported (e.g. stopped in traffic).
    if (position && last.position) return haversineM(position, last.position) < this.options.cooldownMeters;
    return false;
  }
}
