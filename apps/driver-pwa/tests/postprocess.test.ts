import { describe, expect, it } from "vitest";
import {
  decode,
  letterbox,
  nms,
  suppressByContext,
  toCHW,
  toDetections,
  type Detection,
} from "../src/detection/postprocess";

describe("suppressByContext", () => {
  const det = (label: string, box: Detection["box"]): Detection => ({ label, classId: 0, score: 0.6, box });

  it("drops obstacles that are a person, keeps real obstacles and potholes", () => {
    const person = det("person", [0.4, 0.2, 0.6, 0.9]);
    const onPerson = det("obstacle", [0.42, 0.3, 0.58, 0.85]);
    const rocks = det("obstacle", [0.05, 0.7, 0.3, 0.95]);
    const pothole = det("pothole", [0.45, 0.8, 0.55, 0.9]); // even under the person
    const { kept, suppressed } = suppressByContext([onPerson, rocks, pothole], [person]);
    expect(suppressed).toEqual([onPerson]);
    expect(kept).toEqual([rocks, pothole]);
  });

  it("keeps everything when no person or vehicle is present", () => {
    const rocks = det("obstacle", [0.1, 0.6, 0.4, 0.9]);
    expect(suppressByContext([rocks], []).kept).toEqual([rocks]);
  });
});

describe("letterbox", () => {
  it("keeps aspect ratio and centres the image (same rounding as the server)", () => {
    expect(letterbox(1280, 720, 640)).toEqual({ scale: 0.5, padX: 0, padY: 140, srcWidth: 1280, srcHeight: 720 });
  });
});

describe("decode", () => {
  it("filters end-to-end rows by score", () => {
    const data = new Float32Array([10, 10, 50, 50, 0.9, 1, 0, 0, 5, 5, 0.1, 0]);
    expect(decode(data, [1, 2, 6], "end2end", 0.25)).toEqual([[10, 10, 50, 50, expect.closeTo(0.9, 5), 1]]);
  });

  it("decodes the raw layout with class-aware NMS", () => {
    // 4 anchors, channels: cx, cy, w, h, score_pothole, score_obstacle (channel-major)
    const anchors = [
      [100, 100, 20, 20, 0.9, 0.05],
      [101, 101, 20, 20, 0.8, 0.05], // duplicate pothole -> suppressed
      [101, 101, 20, 20, 0.05, 0.7], // obstacle at the same place -> kept
      [300, 300, 20, 20, 0.1, 0.1], // below threshold
    ];
    const data = new Float32Array(6 * 4);
    anchors.forEach((values, a) => values.forEach((v, c) => (data[c * 4 + a] = v)));
    const rows = decode(data, [1, 6, 4], "raw", 0.25);
    expect(rows).toHaveLength(2);
    expect(rows[0].slice(0, 4)).toEqual([90, 90, 110, 110]);
    expect(rows[0][5]).toBe(0);
    expect(rows[1][5]).toBe(1);
  });
});

describe("nms", () => {
  it("keeps non-overlapping boxes", () => {
    const rows = nms(
      [
        [0, 0, 10, 10, 0.9, 0],
        [1, 1, 11, 11, 0.8, 0],
        [50, 50, 60, 60, 0.7, 0],
      ],
      0.5,
    );
    expect(rows.map((r) => r[4])).toEqual([0.9, 0.7]);
  });
});

describe("toDetections", () => {
  it("maps letterboxed pixels back to normalized source coordinates", () => {
    const lb = letterbox(1280, 720, 640);
    const [detection] = toDetections([[0, 140, 320, 320, 0.8, 0]], lb, ["pothole", "obstacle"]);
    expect(detection.label).toBe("pothole");
    expect(detection.box[0]).toBeCloseTo(0);
    expect(detection.box[1]).toBeCloseTo(0);
    expect(detection.box[2]).toBeCloseTo(0.5);
    expect(detection.box[3]).toBeCloseTo(0.5);
  });
});

describe("toCHW", () => {
  it("converts RGBA to planar RGB in [0, 1]", () => {
    const rgba = new Uint8ClampedArray([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255]);
    const chw = toCHW(rgba, 2);
    expect(Array.from(chw.slice(0, 4))).toEqual([1, 0, 0, 1]); // R plane
    expect(Array.from(chw.slice(4, 8))).toEqual([0, 1, 0, 1]); // G plane
    expect(Array.from(chw.slice(8, 12))).toEqual([0, 0, 1, 1]); // B plane
  });
});
