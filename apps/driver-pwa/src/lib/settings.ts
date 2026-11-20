// Per-device preferences, kept in localStorage (a convenience only: defaults always work).
import { DEFAULT_API_URL } from "../config";

export type LocationSource = "gps" | "route";

export interface Settings {
  apiUrl: string;
  voice: boolean;
  locationSource: LocationSource;
  routeStartKm: number;
  routeSpeedKmh: number;
  alertDistanceM: number;
  minScore: number;
  sendPhotos: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  apiUrl: DEFAULT_API_URL,
  voice: true,
  locationSource: "gps",
  routeStartKm: 35,
  routeSpeedKmh: 40,
  alertDistanceM: 500,
  minScore: 0.35,
  sendPhotos: true,
};

const KEY = "viasegura.settings.v1";

export function loadSettings(): Settings {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return stored ? { ...DEFAULT_SETTINGS, ...stored } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    // Private mode / storage blocked: settings simply do not persist.
  }
}
