// Which nearby hazards deserve an alert now, and how to say it (voice, vibration).
import { angleDiff, bearingDeg, haversineM, type LngLat } from "./geo";

export interface AlertHazard {
  id: string;
  type: "pothole" | "obstacle";
  location: LngLat;
}

export interface Fix {
  point: LngLat;
  heading: number | null; // degrees, null when unknown
  speedMs: number | null;
}

export interface AlertOptions {
  distanceM: number;
  repeatMs: number;
  headingToleranceDeg: number;
}

export interface DueAlert {
  hazard: AlertHazard;
  distanceM: number;
}

/** Hazards within range, ahead of the vehicle when its heading is reliable, not alerted recently. */
export function dueAlerts(
  hazards: AlertHazard[],
  fix: Fix,
  alertedAt: Map<string, number>,
  now: number,
  options: AlertOptions,
): DueAlert[] {
  const headingReliable = fix.heading !== null && (fix.speedMs ?? 0) > 2;
  const due: DueAlert[] = [];
  for (const hazard of hazards) {
    const distance = haversineM(fix.point, hazard.location);
    if (distance > options.distanceM) continue;
    const last = alertedAt.get(hazard.id);
    if (last !== undefined && now - last < options.repeatMs) continue;
    if (headingReliable && distance > 40) {
      const toHazard = bearingDeg(fix.point, hazard.location);
      if (angleDiff(toHazard, fix.heading as number) > options.headingToleranceDeg) continue; // behind
    }
    due.push({ hazard, distanceM: distance });
  }
  return due.sort((a, b) => a.distanceM - b.distanceM);
}

const LABELS: Record<AlertHazard["type"], { short: string; spoken: string }> = {
  pothole: { short: "Bache", spoken: "bache" },
  obstacle: { short: "Obstáculo o derrumbe", spoken: "obstáculo o derrumbe" },
};

export function hazardLabel(type: AlertHazard["type"]): string {
  return LABELS[type]?.short ?? type;
}

/** Rounded, easy-to-hear distance ("a 300 metros"). */
export function spokenDistance(distanceM: number): string {
  if (distanceM < 50) return "muy cerca";
  const rounded = distanceM < 200 ? Math.round(distanceM / 10) * 10 : Math.round(distanceM / 50) * 50;
  return `a ${rounded} metros`;
}

export function alertSentence(type: AlertHazard["type"], distanceM: number): string {
  const label = LABELS[type]?.spoken ?? type;
  const advice = type === "obstacle" ? "Reduzca la velocidad." : "Precaución.";
  return `Atención: ${label} ${spokenDistance(distanceM)}. ${advice}`;
}

let spanishVoice: SpeechSynthesisVoice | null | undefined;

function pickSpanishVoice(): SpeechSynthesisVoice | null {
  if (spanishVoice !== undefined) return spanishVoice;
  const voices = typeof speechSynthesis !== "undefined" ? speechSynthesis.getVoices() : [];
  spanishVoice =
    voices.find((v) => v.lang.toLowerCase().startsWith("es-pe")) ??
    voices.find((v) => v.lang.toLowerCase().startsWith("es-419")) ??
    voices.find((v) => v.lang.toLowerCase().startsWith("es")) ??
    null;
  return spanishVoice;
}

export function speak(text: string): void {
  if (typeof speechSynthesis === "undefined") return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "es-PE";
  const voice = pickSpanishVoice();
  if (voice) utterance.voice = voice;
  utterance.rate = 1;
  speechSynthesis.cancel();
  speechSynthesis.speak(utterance);
}

export function vibrate(type: AlertHazard["type"]): void {
  if (typeof navigator !== "undefined" && "vibrate" in navigator) {
    navigator.vibrate(type === "obstacle" ? [400, 150, 400, 150, 400] : [300, 120, 300]);
  }
}
