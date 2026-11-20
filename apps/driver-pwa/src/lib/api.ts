// Typed client for the VíaSegura API.
import type { LngLat } from "./geo";

export type HazardType = "pothole" | "obstacle";

export interface ReportPayload {
  clientReportId: string;
  deviceId: string;
  type: HazardType;
  confidence: number;
  location: { type: "Point"; coordinates: LngLat };
  accuracyM: number | null;
  headingDeg: number | null;
  speedKmh: number | null;
  ts: string;
  modelVersion: string | null;
}

export interface ReportResult {
  reportId: string;
  duplicate: boolean;
  accepted: boolean;
  incidentId: string | null;
  incidentStatus: "pending" | "confirmed" | "resolved" | null;
  distinctDevices: number;
  requiredDevices: number;
  serverCheck: { status: "confirmed" | "rejected" | "skipped"; confidence: number | null; reason: string | null };
  imageUrl: string | null;
}

export interface Incident {
  id: string;
  type: HazardType;
  status: "pending" | "confirmed" | "resolved";
  location: { type: "Point"; coordinates: LngLat };
  reportsCount: number;
  devicesCount: number;
  lastSeen: string;
  segmentName: string | null;
  distanceM: number | null;
}

export interface PostResult {
  status: number; // 0 = network error
  body: ReportResult | { error?: { code: string; message: string } } | null;
}

async function request(url: string, init: RequestInit = {}, timeoutMs = 15_000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export class ApiClient {
  constructor(private readonly baseUrl: string) {}

  private url(path: string): string {
    return `${this.baseUrl.replace(/\/+$/, "")}${path}`;
  }

  async postReport(report: ReportPayload, image: Blob | null): Promise<PostResult> {
    let init: RequestInit;
    if (image) {
      const form = new FormData();
      form.append("report", JSON.stringify(report));
      form.append("image", image, "hazard.jpg");
      init = { method: "POST", body: form };
    } else {
      init = { method: "POST", body: JSON.stringify(report), headers: { "Content-Type": "application/json" } };
    }
    try {
      const response = await request(this.url("/reports"), init);
      const body = await response.json().catch(() => null);
      return { status: response.status, body };
    } catch {
      return { status: 0, body: null };
    }
  }

  async nearby(point: LngLat, radiusM: number): Promise<Incident[]> {
    const query = new URLSearchParams({
      lng: point[0].toFixed(6),
      lat: point[1].toFixed(6),
      radius: String(radiusM),
      limit: "200",
    });
    const response = await request(this.url(`/incidents/nearby?${query}`));
    if (!response.ok) throw new Error(`nearby: HTTP ${response.status}`);
    return response.json();
  }
}
