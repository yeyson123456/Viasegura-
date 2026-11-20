// Tunable constants. Detection thresholds are deliberately conservative: a false report costs a
// road crew a trip, while a missed hazard is usually caught by the next car (consensus).

export const DEFAULT_API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const DETECTION = {
  intervalMs: 250, // pause between analysed frames (the model itself takes most of the time)
  windowFrames: 3, // M: frames considered by the temporal filter
  hitsRequired: 2, // K: frames that must contain the hazard
  cooldownMeters: 60, // do not report the same hazard type again within this distance...
  cooldownMs: 15_000, // ...or this time
};

export const ALERTS = {
  repeatMs: 5 * 60_000, // re-alert the same hazard after 5 minutes
  headingToleranceDeg: 75, // ignore hazards behind the vehicle when the heading is reliable
};

export const SYNC = {
  outboxIntervalMs: 10_000,
  nearbyIntervalMs: 15_000,
  nearbyRadiusM: 5_000, // hazards cached for offline alerts
};

export const MODEL_URL = "/models/hazards.onnx";
export const MODEL_META_URL = "/models/hazards.json";
// COCO context model (people and vehicles): filters false "obstacles" and blurs people in photos.
export const CONTEXT_MODEL_URL = "/models/context.onnx";
export const CONTEXT_META_URL = "/models/context.json";
// Obstacles need more confidence than potholes before they become a report.
export const MIN_SCORE_BY_LABEL: Record<string, number> = { obstacle: 0.45 };
export const CORRIDOR_URL = "/data/corridor.json";
export const DEMO_VIDEO_URL = "/demo/demo-road.webm";
