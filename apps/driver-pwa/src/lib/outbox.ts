// Offline-first reporting: every report is written to IndexedDB first, then sent when there is
// signal. Retries are safe because the API is idempotent on (deviceId, clientReportId).
import type { ApiClient, ReportPayload, ReportResult } from "./api";
import { getDb, type OutboxItem } from "./db";

export interface SyncSummary {
  sent: number;
  dropped: number;
  remaining: number;
  lastResult: ReportResult | null;
  offline: boolean;
}

export async function enqueue(report: ReportPayload, image: Blob | null): Promise<void> {
  const item: OutboxItem = { clientReportId: report.clientReportId, report, image, createdAt: Date.now(), attempts: 0 };
  await (await getDb()).put("outbox", item);
}

export async function pendingCount(): Promise<number> {
  return (await getDb()).count("outbox");
}

let syncing: Promise<SyncSummary> | null = null;

/** Send queued reports oldest-first; stops at the first network/server failure. */
export function syncOutbox(api: ApiClient): Promise<SyncSummary> {
  syncing ??= doSync(api).finally(() => {
    syncing = null;
  });
  return syncing;
}

async function doSync(api: ApiClient): Promise<SyncSummary> {
  const db = await getDb();
  const items = await db.getAllFromIndex("outbox", "byCreatedAt");
  const summary: SyncSummary = { sent: 0, dropped: 0, remaining: items.length, lastResult: null, offline: false };
  for (const item of items) {
    const { status, body } = await api.postReport(item.report, item.image);
    if (status >= 200 && status < 300) {
      await db.delete("outbox", item.clientReportId);
      summary.sent += 1;
      summary.lastResult = body as ReportResult;
    } else if (status >= 400 && status < 500 && status !== 408 && status !== 429) {
      // Permanent rejection (e.g. too old, invalid): keeping it would block the queue forever.
      await db.delete("outbox", item.clientReportId);
      summary.dropped += 1;
    } else {
      await db.put("outbox", { ...item, attempts: item.attempts + 1, lastError: `HTTP ${status}` });
      summary.offline = status === 0;
      break;
    }
    summary.remaining -= 1;
  }
  return summary;
}
