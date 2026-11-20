import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import type { ApiClient, PostResult, ReportPayload } from "../src/lib/api";
import { getDb } from "../src/lib/db";
import { enqueue, pendingCount, syncOutbox } from "../src/lib/outbox";

const report = (id: string): ReportPayload => ({
  clientReportId: id,
  deviceId: "dev-test-0001",
  type: "pothole",
  confidence: 0.8,
  location: { type: "Point", coordinates: [-76.1, -9.7] },
  accuracyM: 5,
  headingDeg: null,
  speedKmh: null,
  ts: new Date().toISOString(),
  modelVersion: null,
});

function fakeApi(statuses: number[]): ApiClient & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    async postReport(payload: ReportPayload): Promise<PostResult> {
      calls.push(payload.clientReportId);
      const status = statuses.shift() ?? 201;
      return { status, body: status < 300 ? ({ accepted: true, incidentStatus: "pending" } as never) : null };
    },
  } as unknown as ApiClient & { calls: string[] };
}

beforeEach(async () => {
  await (await getDb()).clear("outbox");
});

describe("offline outbox", () => {
  it("keeps reports while offline and sends them in order when the signal returns", async () => {
    await enqueue(report("r1"), null);
    await enqueue(report("r2"), null);

    const offline = await syncOutbox(fakeApi([0]));
    expect(offline.offline).toBe(true);
    expect(await pendingCount()).toBe(2);

    const api = fakeApi([201, 200]);
    const online = await syncOutbox(api);
    expect(api.calls).toEqual(["r1", "r2"]);
    expect(online.sent).toBe(2);
    expect(await pendingCount()).toBe(0);
  });

  it("drops permanently rejected reports instead of blocking the queue", async () => {
    await enqueue(report("bad"), null);
    await enqueue(report("good"), null);

    const summary = await syncOutbox(fakeApi([422, 201]));

    expect(summary.dropped).toBe(1);
    expect(summary.sent).toBe(1);
    expect(await pendingCount()).toBe(0);
  });

  it("keeps the report and stops on server errors", async () => {
    await enqueue(report("r1"), null);

    const summary = await syncOutbox(fakeApi([503]));

    expect(summary.sent).toBe(0);
    expect(await pendingCount()).toBe(1);
  });
});
