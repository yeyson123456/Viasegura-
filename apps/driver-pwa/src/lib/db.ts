// IndexedDB: offline outbox of reports and the cache of confirmed hazards for offline alerts.
import { openDB, type DBSchema, type IDBPDatabase } from "idb";
import type { Incident, ReportPayload } from "./api";

export interface OutboxItem {
  clientReportId: string;
  report: ReportPayload;
  image: Blob | null;
  createdAt: number;
  attempts: number;
  lastError?: string;
}

interface ViaSeguraDB extends DBSchema {
  outbox: { key: string; value: OutboxItem; indexes: { byCreatedAt: number } };
  hazards: { key: string; value: Incident };
}

let dbPromise: Promise<IDBPDatabase<ViaSeguraDB>> | null = null;

export function getDb(): Promise<IDBPDatabase<ViaSeguraDB>> {
  dbPromise ??= openDB<ViaSeguraDB>("viasegura", 1, {
    upgrade(db) {
      const outbox = db.createObjectStore("outbox", { keyPath: "clientReportId" });
      outbox.createIndex("byCreatedAt", "createdAt");
      db.createObjectStore("hazards", { keyPath: "id" });
    },
  });
  return dbPromise;
}

/** Replace the cached hazards with a fresh server answer. */
export async function cacheHazards(incidents: Incident[]): Promise<void> {
  const db = await getDb();
  const tx = db.transaction("hazards", "readwrite");
  await tx.store.clear();
  await Promise.all(incidents.map((incident) => tx.store.put(incident)));
  await tx.done;
}

export async function cachedHazards(): Promise<Incident[]> {
  return (await getDb()).getAll("hazards");
}
