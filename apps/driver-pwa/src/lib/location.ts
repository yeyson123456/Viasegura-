// Location sources: the phone's GPS (works in airplane mode, GNSS needs no network) or a
// simulated drive along the real Huánuco – Tingo María corridor for indoor demos.
import { CORRIDOR_URL } from "../config";
import { lineLengthM, positionAlong, type LngLat } from "./geo";
import type { LocationSource } from "./settings";

export interface LocationFix {
  point: LngLat;
  accuracyM: number | null;
  heading: number | null;
  speedMs: number | null;
  timestamp: number;
  source: LocationSource;
}

export interface RouteOptions {
  startKm: number;
  speedKmh: number;
}

let corridor: LngLat[] | null = null;

export async function loadCorridor(): Promise<LngLat[]> {
  if (!corridor) {
    const response = await fetch(CORRIDOR_URL);
    corridor = (await response.json()).coordinates as LngLat[];
  }
  return corridor;
}

export function startLocation(
  source: LocationSource,
  route: RouteOptions,
  onFix: (fix: LocationFix) => void,
  onError: (message: string) => void,
): () => void {
  if (source === "gps") {
    if (!("geolocation" in navigator)) {
      onError("Este dispositivo no tiene GPS disponible.");
      return () => undefined;
    }
    const id = navigator.geolocation.watchPosition(
      (position) =>
        onFix({
          point: [position.coords.longitude, position.coords.latitude],
          accuracyM: position.coords.accuracy ?? null,
          heading: Number.isFinite(position.coords.heading) ? position.coords.heading : null,
          speedMs: Number.isFinite(position.coords.speed) ? position.coords.speed : null,
          timestamp: position.timestamp,
          source,
        }),
      (error) =>
        onError(
          error.code === error.PERMISSION_DENIED
            ? "Permiso de ubicación denegado. Actívalo para reportar peligros."
            : "Buscando señal GPS…",
        ),
      { enableHighAccuracy: true, maximumAge: 1_000, timeout: 20_000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }

  // Simulated drive: advance along the corridor once per second, looping at the end.
  let stopped = false;
  let timer: ReturnType<typeof setInterval> | undefined;
  loadCorridor()
    .then((line) => {
      if (stopped) return;
      const total = lineLengthM(line);
      let travelled = (route.startKm * 1000) % total;
      const speedMs = route.speedKmh / 3.6;
      const emit = () => {
        const { point, heading } = positionAlong(line, travelled);
        onFix({ point, accuracyM: 5, heading, speedMs, timestamp: Date.now(), source });
        travelled = (travelled + speedMs) % total;
      };
      emit();
      timer = setInterval(emit, 1_000);
    })
    .catch(() => onError("No se pudo cargar la ruta simulada."));
  return () => {
    stopped = true;
    if (timer) clearInterval(timer);
  };
}
