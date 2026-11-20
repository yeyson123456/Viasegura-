// Main-thread facade over the detection worker (promise per request).
import { MODEL_META_URL, MODEL_URL } from "../config";
import type { Box } from "../privacy/anonymize";
import type { Detection, ModelMeta } from "./postprocess";
import type { WorkerRequest } from "./worker";

export interface LoadInfo {
  meta: ModelMeta;
  threads: number;
  isolated: boolean;
}

export interface DetectResult {
  detections: Detection[];
  inferenceMs: number;
  totalMs: number;
}

export interface BenchmarkResult {
  runs: number;
  medianMs: number;
  p90Ms: number;
  threads: number;
}

type Pending = { resolve: (value: never) => void; reject: (reason: Error) => void };

// Payload a request carries, without the id the facade adds itself.
type Payload =
  | { type: "load"; modelUrl: string; metaUrl: string }
  | { type: "detect"; frame: ImageBitmap; minScore: number }
  | { type: "anonymize"; box: Box }
  | { type: "benchmark"; runs: number };

export class Detector {
  private worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  private pending = new Map<number, Pending>();
  private nextId = 1;
  meta: ModelMeta | null = null;

  constructor() {
    this.worker.onmessage = (event: MessageEvent) => {
      const { id, type } = event.data;
      const pending = this.pending.get(id);
      if (!pending) return;
      this.pending.delete(id);
      if (type === "error") pending.reject(new Error(event.data.message));
      else pending.resolve(event.data as never);
    };
  }

  private call<T>(payload: Payload, transfer: Transferable[] = []): Promise<T> {
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (value: never) => void, reject });
      this.worker.postMessage({ ...payload, id } as WorkerRequest, transfer);
    });
  }

  async load(): Promise<LoadInfo> {
    const info = await this.call<LoadInfo>({ type: "load", modelUrl: MODEL_URL, metaUrl: MODEL_META_URL });
    this.meta = info.meta;
    return info;
  }

  /** The frame is transferred to the worker (zero-copy) and must not be used afterwards. */
  detect(frame: ImageBitmap, minScore: number): Promise<DetectResult> {
    return this.call<DetectResult>({ type: "detect", frame, minScore }, [frame]);
  }

  async anonymize(box: Box): Promise<Blob | null> {
    const result = await this.call<{ blob: Blob | null }>({ type: "anonymize", box });
    return result.blob;
  }

  benchmark(runs = 20): Promise<BenchmarkResult> {
    return this.call<BenchmarkResult>({ type: "benchmark", runs });
  }

  terminate(): void {
    this.worker.terminate();
    for (const pending of this.pending.values()) pending.reject(new Error("detector terminated"));
    this.pending.clear();
  }
}
