import { describe, expect, it } from "vitest";
import type { Detection } from "../src/detection/postprocess";
import { HazardTracker } from "../src/detection/tracker";
import { alertSentence, dueAlerts, spokenDistance } from "../src/lib/alerts";
import { angleDiff, bearingDeg, haversineM, lineLengthM, positionAlong, type LngLat } from "../src/lib/geo";
import { planCrop } from "../src/privacy/anonymize";

const pothole = (score: number): Detection => ({ label: "pothole", classId: 0, score, box: [0.4, 0.6, 0.5, 0.7] });
const options = { windowFrames: 3, hitsRequired: 2, minScore: 0.35, cooldownMeters: 60, cooldownMs: 15_000 };

describe("HazardTracker", () => {
  it("needs K of M frames before reporting", () => {
    const tracker = new HazardTracker(options);
    expect(tracker.update([pothole(0.8)], 0, null)).toHaveLength(0);
    expect(tracker.update([pothole(0.7)], 300, null)).toHaveLength(1);
  });

  it("ignores low-confidence detections", () => {
    const tracker = new HazardTracker(options);
    tracker.update([pothole(0.2)], 0, null);
    expect(tracker.update([pothole(0.3)], 300, null)).toHaveLength(0);
  });

  it("does not report the same hazard type again until the car has moved on", () => {
    const tracker = new HazardTracker(options);
    const here: LngLat = [-76.1, -9.7];
    tracker.update([pothole(0.8)], 0, here);
    expect(tracker.update([pothole(0.8)], 300, here)).toHaveLength(1);
    expect(tracker.update([pothole(0.8)], 20_000, here)).toHaveLength(0); // same place
    const farther: LngLat = [-76.1, -9.6985]; // ~170 m north
    expect(tracker.update([pothole(0.8)], 21_000, farther)).toHaveLength(1);
  });
});

describe("geo", () => {
  it("measures distances and bearings", () => {
    expect(haversineM([-76, -9], [-76, -10])).toBeCloseTo(111_195, -2);
    expect(bearingDeg([-76, -10], [-76, -9])).toBeCloseTo(0, 5); // due north
    expect(angleDiff(350, 10)).toBe(20);
  });

  it("walks along a polyline", () => {
    const line: LngLat[] = [
      [-76, -10],
      [-76, -9.99],
      [-76, -9.98],
    ];
    const total = lineLengthM(line);
    const middle = positionAlong(line, total / 2);
    expect(middle.point[1]).toBeCloseTo(-9.99, 4);
    expect(middle.heading).toBeCloseTo(0, 3);
    expect(positionAlong(line, total * 2).point).toEqual(line[2]);
  });
});

describe("dueAlerts", () => {
  const hazard = { id: "a", type: "obstacle" as const, location: [-76, -9.997] as LngLat }; // ~330 m north
  const opts = { distanceM: 500, repeatMs: 300_000, headingToleranceDeg: 75 };

  it("alerts for a hazard ahead within range, once", () => {
    const alerted = new Map<string, number>();
    const fix = { point: [-76, -10] as LngLat, heading: 0, speedMs: 10 };
    const due = dueAlerts([hazard], fix, alerted, 0, opts);
    expect(due).toHaveLength(1);
    expect(due[0].distanceM).toBeGreaterThan(300);
    alerted.set("a", 0);
    expect(dueAlerts([hazard], fix, alerted, 60_000, opts)).toHaveLength(0);
  });

  it("skips hazards behind a moving vehicle and out of range", () => {
    const southbound = { point: [-76, -10] as LngLat, heading: 180, speedMs: 10 };
    expect(dueAlerts([hazard], southbound, new Map(), 0, opts)).toHaveLength(0);
    expect(dueAlerts([hazard], { ...southbound, heading: 0 }, new Map(), 0, { ...opts, distanceM: 200 })).toHaveLength(0);
  });

  it("uses distance only when the heading is unreliable (stopped)", () => {
    const stopped = { point: [-76, -10] as LngLat, heading: 180, speedMs: 0 };
    expect(dueAlerts([hazard], stopped, new Map(), 0, opts)).toHaveLength(1);
  });

  it("speaks short Spanish sentences", () => {
    expect(spokenDistance(327)).toBe("a 350 metros");
    expect(spokenDistance(30)).toBe("muy cerca");
    expect(alertSentence("pothole", 120)).toBe("Atención: bache a 120 metros. Precaución.");
  });
});

describe("planCrop (privacy)", () => {
  it("keeps a bounded crop around the hazard, never the full HD frame", () => {
    const plan = planCrop([0.45, 0.6, 0.55, 0.7], 1280, 720);
    expect(Math.max(plan.out.w, plan.out.h)).toBeLessThanOrEqual(480);
    expect(plan.crop.w).toBeLessThan(1280);
    expect(plan.hazard.x).toBeGreaterThan(0);
    expect(plan.hazard.x + plan.hazard.w).toBeLessThanOrEqual(plan.out.w + 1e-6);
  });

  it("stays inside the frame near the edges", () => {
    const plan = planCrop([0.9, 0.9, 1, 1], 1280, 720);
    expect(plan.crop.x + plan.crop.w).toBeLessThanOrEqual(1280);
    expect(plan.crop.y + plan.crop.h).toBeLessThanOrEqual(720);
  });
});
