// Anonymous device id, regenerated every day: the server can count distinct devices for
// consensus, but cannot link one driver's reports across days.
const KEY = "viasegura.device.v1";

export function deviceId(now: Date = new Date()): string {
  const day = now.toISOString().slice(0, 10);
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (stored?.day === day && typeof stored.id === "string") return stored.id;
  } catch {
    // ignore corrupt or blocked storage
  }
  const id = `dev-${crypto.randomUUID()}`;
  try {
    localStorage.setItem(KEY, JSON.stringify({ day, id }));
  } catch {
    // storage blocked: a fresh id per session is still anonymous
  }
  return id;
}
