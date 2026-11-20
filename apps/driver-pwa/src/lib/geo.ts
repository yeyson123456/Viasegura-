// Small geodesy helpers (WGS84 sphere approximation, good to a few metres at road scale).

const EARTH_RADIUS_M = 6_371_008.8;
const rad = (deg: number) => (deg * Math.PI) / 180;
const deg = (radians: number) => (radians * 180) / Math.PI;

export type LngLat = [number, number];

export function haversineM(a: LngLat, b: LngLat): number {
  const dPhi = rad(b[1] - a[1]);
  const dLambda = rad(b[0] - a[0]);
  const h =
    Math.sin(dPhi / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLambda / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Initial bearing from a to b, degrees clockwise from north in [0, 360). */
export function bearingDeg(a: LngLat, b: LngLat): number {
  const phi1 = rad(a[1]);
  const phi2 = rad(b[1]);
  const dLambda = rad(b[0] - a[0]);
  const y = Math.sin(dLambda) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLambda);
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

/** Smallest absolute difference between two headings, in [0, 180]. */
export function angleDiff(a: number, b: number): number {
  const diff = Math.abs(a - b) % 360;
  return diff > 180 ? 360 - diff : diff;
}

export function lineLengthM(line: LngLat[]): number {
  let total = 0;
  for (let i = 1; i < line.length; i++) total += haversineM(line[i - 1], line[i]);
  return total;
}

/** Point and heading at `distanceM` metres along a polyline (clamped to its ends). */
export function positionAlong(line: LngLat[], distanceM: number): { point: LngLat; heading: number } {
  let remaining = Math.max(0, distanceM);
  for (let i = 1; i < line.length; i++) {
    const a = line[i - 1];
    const b = line[i];
    const step = haversineM(a, b);
    if (remaining <= step && step > 0) {
      const t = remaining / step;
      return { point: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], heading: bearingDeg(a, b) };
    }
    remaining -= step;
  }
  const last = line[line.length - 1];
  return { point: last, heading: line.length > 1 ? bearingDeg(line[line.length - 2], last) : 0 };
}
