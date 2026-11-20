// Detection worker: ONNX Runtime Web (WASM, multi-threaded when cross-origin isolated) runs the
// same hazards.onnx as the server, off the UI thread. An optional COCO "context" model recognises
// people and vehicles: obstacles that are really a person/vehicle are discarded, and people and
// vehicles are blurred in uploaded photos.
import * as ort from "onnxruntime-web/wasm";
import { anonymize, type Box } from "../privacy/anonymize";
import {
  decode,
  letterbox,
  suppressByContext,
  toCHW,
  toDetections,
  type Detection,
  type Letterbox,
  type ModelMeta,
} from "./postprocess";

export type WorkerRequest =
  | { type: "load"; id: number; modelUrl: string; metaUrl: string; contextUrl: string; contextMetaUrl: string }
  | { type: "detect"; id: number; frame: ImageBitmap; minScore: number }
  | { type: "anonymize"; id: number; box: Box }
  | { type: "benchmark"; id: number; runs: number };

interface WorkerScope {
  postMessage(message: unknown, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null;
  crossOriginIsolated: boolean;
}
const scope = self as unknown as WorkerScope;

interface ContextMeta extends ModelMeta {
  context_classes: string[];
}

let session: ort.InferenceSession | null = null;
let meta: ModelMeta | null = null;
let context: { session: ort.InferenceSession; meta: ContextMeta } | null = null;
let lastFrame: ImageBitmap | null = null;
const canvases = new Map<number, OffscreenCanvas>();

function inputTensor(frame: ImageBitmap | null, size: number): { tensor: ort.Tensor; lb: Letterbox } {
  let canvas = canvases.get(size);
  if (!canvas) {
    canvas = new OffscreenCanvas(size, size);
    canvases.set(size, canvas);
  }
  const ctx = canvas.getContext("2d", { willReadFrequently: true }) as OffscreenCanvasRenderingContext2D;
  ctx.fillStyle = "rgb(114,114,114)";
  ctx.fillRect(0, 0, size, size);
  const lb = letterbox(frame?.width ?? size, frame?.height ?? size, size);
  if (frame) {
    ctx.drawImage(frame, lb.padX, lb.padY, Math.round(frame.width * lb.scale), Math.round(frame.height * lb.scale));
  }
  const pixels = ctx.getImageData(0, 0, size, size).data;
  return { tensor: new ort.Tensor("float32", toCHW(pixels, size), [1, 3, size, size]), lb };
}

async function createSession(url: string): Promise<ort.InferenceSession> {
  const model = await (await fetch(url)).arrayBuffer();
  return ort.InferenceSession.create(model, { executionProviders: ["wasm"], graphOptimizationLevel: "all" });
}

async function loadContext(url: string, metaUrl: string) {
  try {
    const response = await fetch(metaUrl);
    if (!response.ok) return null;
    const contextMeta = (await response.json()) as ContextMeta;
    return { session: await createSession(url), meta: contextMeta };
  } catch {
    return null; // optional: the app works without it
  }
}

/** People and vehicles in the frame (normalized boxes). */
async function contextBoxes(frame: ImageBitmap): Promise<Detection[]> {
  if (!context) return [];
  const { tensor, lb } = inputTensor(frame, context.meta.imgsz);
  const output = (await context.session.run({ [context.meta.input_name]: tensor }))[context.meta.output_name];
  const wanted = new Set(context.meta.context_classes);
  const rows = decode(output.data as Float32Array, output.dims, "end2end", 0.35);
  return toDetections(rows, lb, context.meta.classes).filter((d) => wanted.has(d.label));
}

scope.onmessage = async (event) => {
  const message = event.data;
  try {
    if (message.type === "load") {
      // The .wasm runtime is bundled by Vite (hashed asset, precached by the service worker).
      const cores = (navigator as Navigator & { hardwareConcurrency?: number }).hardwareConcurrency ?? 2;
      ort.env.wasm.numThreads = scope.crossOriginIsolated ? Math.max(1, Math.min(4, cores - 1)) : 1;
      meta = (await (await fetch(message.metaUrl)).json()) as ModelMeta;
      session = await createSession(message.modelUrl);
      const hazardModel = session;
      await hazardModel.run({ [meta.input_name]: inputTensor(null, meta.imgsz).tensor }); // warm-up
      context = await loadContext(message.contextUrl, message.contextMetaUrl);
      scope.postMessage({
        type: "loaded",
        id: message.id,
        meta,
        threads: ort.env.wasm.numThreads,
        isolated: scope.crossOriginIsolated,
        contextModel: Boolean(context),
      });
    } else if (message.type === "detect") {
      if (!session || !meta) throw new Error("model not loaded");
      const started = performance.now();
      const { tensor, lb } = inputTensor(message.frame, meta.imgsz);
      lastFrame?.close();
      lastFrame = message.frame; // kept for the privacy crop if this frame becomes a report
      const inferenceStart = performance.now();
      const output = (await session.run({ [meta.input_name]: tensor }))[meta.output_name];
      const inferenceMs = performance.now() - inferenceStart;
      const rows = decode(output.data as Float32Array, output.dims, meta.output_layout, message.minScore);
      let detections = toDetections(rows, lb, meta.classes);
      let people: Detection[] = [];
      let suppressed = 0;
      // Only pay for the context model when an obstacle shows up.
      if (context && detections.some((d) => d.label === "obstacle")) {
        people = await contextBoxes(message.frame);
        const result = suppressByContext(detections, people);
        detections = result.kept;
        suppressed = result.suppressed.length;
      }
      scope.postMessage({
        type: "detections",
        id: message.id,
        detections,
        context: people,
        suppressed,
        inferenceMs,
        totalMs: performance.now() - started,
      });
    } else if (message.type === "anonymize") {
      const blob = lastFrame ? await anonymize(lastFrame, message.box, await contextBoxes(lastFrame)) : null;
      scope.postMessage({ type: "anonymized", id: message.id, blob });
    } else if (message.type === "benchmark") {
      if (!session || !meta) throw new Error("model not loaded");
      const { tensor } = inputTensor(null, meta.imgsz);
      const times: number[] = [];
      for (let i = 0; i < message.runs; i++) {
        const start = performance.now();
        await session.run({ [meta.input_name]: tensor });
        times.push(performance.now() - start);
      }
      times.sort((a, b) => a - b);
      scope.postMessage({
        type: "benchmark",
        id: message.id,
        runs: times.length,
        medianMs: times[Math.floor(times.length / 2)],
        p90Ms: times[Math.min(times.length - 1, Math.floor(times.length * 0.9))],
        threads: ort.env.wasm.numThreads,
      });
    }
  } catch (error) {
    scope.postMessage({ type: "error", id: message.id, message: String(error) });
  }
};
