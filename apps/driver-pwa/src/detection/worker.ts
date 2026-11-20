// Detection worker: ONNX Runtime Web (WASM, multi-threaded when cross-origin isolated) runs the
// same hazards.onnx as the server, off the UI thread.
import * as ort from "onnxruntime-web/wasm";
import { anonymize, type Box } from "../privacy/anonymize";
import { decode, letterbox, toCHW, toDetections, type ModelMeta } from "./postprocess";

export type WorkerRequest =
  | { type: "load"; id: number; modelUrl: string; metaUrl: string }
  | { type: "detect"; id: number; frame: ImageBitmap; minScore: number }
  | { type: "anonymize"; id: number; box: Box }
  | { type: "benchmark"; id: number; runs: number };

interface WorkerScope {
  postMessage(message: unknown, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null;
  crossOriginIsolated: boolean;
}
const scope = self as unknown as WorkerScope;

let session: ort.InferenceSession | null = null;
let meta: ModelMeta | null = null;
let canvas: OffscreenCanvas | null = null;
let lastFrame: ImageBitmap | null = null;

function inputTensor(frame: ImageBitmap | null, size: number) {
  canvas ??= new OffscreenCanvas(size, size);
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

async function run(tensor: ort.Tensor) {
  if (!session || !meta) throw new Error("model not loaded");
  const outputs = await session.run({ [meta.input_name]: tensor });
  return outputs[meta.output_name];
}

scope.onmessage = async (event) => {
  const message = event.data;
  try {
    if (message.type === "load") {
      // The .wasm runtime is bundled by Vite (hashed asset, precached by the service worker).
      const cores = (navigator as Navigator & { hardwareConcurrency?: number }).hardwareConcurrency ?? 2;
      ort.env.wasm.numThreads = scope.crossOriginIsolated ? Math.max(1, Math.min(4, cores - 1)) : 1;
      meta = (await (await fetch(message.metaUrl)).json()) as ModelMeta;
      const model = await (await fetch(message.modelUrl)).arrayBuffer();
      session = await ort.InferenceSession.create(model, {
        executionProviders: ["wasm"],
        graphOptimizationLevel: "all",
      });
      await run(inputTensor(null, meta.imgsz).tensor); // warm-up
      scope.postMessage({
        type: "loaded",
        id: message.id,
        meta,
        threads: ort.env.wasm.numThreads,
        isolated: scope.crossOriginIsolated,
      });
    } else if (message.type === "detect") {
      if (!meta) throw new Error("model not loaded");
      const started = performance.now();
      const { tensor, lb } = inputTensor(message.frame, meta.imgsz);
      lastFrame?.close();
      lastFrame = message.frame; // kept for the privacy crop if this frame becomes a report
      const inferenceStart = performance.now();
      const output = await run(tensor);
      const inferenceMs = performance.now() - inferenceStart;
      const rows = decode(output.data as Float32Array, output.dims, meta.output_layout, message.minScore);
      const detections = toDetections(rows, lb, meta.classes);
      scope.postMessage({
        type: "detections",
        id: message.id,
        detections,
        inferenceMs,
        totalMs: performance.now() - started,
      });
    } else if (message.type === "anonymize") {
      const blob = lastFrame ? await anonymize(lastFrame, message.box) : null;
      scope.postMessage({ type: "anonymized", id: message.id, blob });
    } else if (message.type === "benchmark") {
      if (!meta) throw new Error("model not loaded");
      const { tensor } = inputTensor(null, meta.imgsz);
      const times: number[] = [];
      for (let i = 0; i < message.runs; i++) {
        const start = performance.now();
        await run(tensor);
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
