import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ALERTS, DEMO_VIDEO_URL, DETECTION, MIN_SCORE_BY_LABEL, SYNC } from "./config";
import { Detector, type BenchmarkResult, type LoadInfo } from "./detection/detector";
import type { Detection } from "./detection/postprocess";
import { HazardTracker } from "./detection/tracker";
import { alertSentence, dueAlerts, hazardLabel, speak, vibrate } from "./lib/alerts";
import { ApiClient, type HazardType, type Incident, type ReportPayload, type ReportResult } from "./lib/api";
import { cacheHazards, cachedHazards } from "./lib/db";
import { deviceId } from "./lib/device";
import { haversineM } from "./lib/geo";
import { startLocation, type LocationFix } from "./lib/location";
import { enqueue, pendingCount, syncOutbox } from "./lib/outbox";
import { loadSettings, saveSettings, type Settings } from "./lib/settings";
import { AlertOverlay, HazardList, Icons, SettingsSheet, StatusBar } from "./ui/components";

type Mode = "idle" | "camera" | "demo";
type ModelState = { status: "loading" | "ready" | "error"; info?: LoadInfo; error?: string };

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function describe(result: ReportResult): string {
  if (!result.accepted) return "El servidor no confirmó el peligro en la foto (descartado).";
  if (result.incidentStatus === "confirmed") return "Incidente CONFIRMADO: ya se avisa a otros conductores.";
  return `Incidente pendiente: ${result.distinctDevices}/${result.requiredDevices} dispositivos lo han visto.`;
}

const CONTEXT_LABELS: Record<string, string> = {
  person: "Persona",
  bicycle: "Bicicleta",
  car: "Auto",
  motorcycle: "Moto",
  bus: "Bus",
  truck: "Camión",
};

function drawDetections(
  canvas: HTMLCanvasElement,
  width: number,
  height: number,
  detections: Detection[],
  context: Detection[] = [],
) {
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, width, height);
  const line = Math.max(2, Math.round(width / 320));
  ctx.font = `600 ${Math.max(14, Math.round(width / 40))}px "IBM Plex Sans", system-ui, sans-serif`;
  // People and vehicles: recognised and ignored (never reported as obstacles).
  ctx.setLineDash([10, 6]);
  for (const c of context) {
    const [x1, y1, x2, y2] = [c.box[0] * width, c.box[1] * height, c.box[2] * width, c.box[3] * height];
    ctx.strokeStyle = "#7fb2e5";
    ctx.lineWidth = line;
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.fillStyle = "#7fb2e5";
    ctx.fillText(`${CONTEXT_LABELS[c.label] ?? c.label} · ignorado`, x1 + 6, Math.min(height - 8, y2 - 8));
  }
  ctx.setLineDash([]);
  for (const d of detections) {
    const [x1, y1, x2, y2] = [d.box[0] * width, d.box[1] * height, d.box[2] * width, d.box[3] * height];
    const color = d.label === "obstacle" ? "#e5484d" : "#f2b705";
    ctx.strokeStyle = color;
    ctx.lineWidth = line;
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    const text = `${hazardLabel(d.label as HazardType)} ${Math.round(d.score * 100)}%`;
    const textWidth = ctx.measureText(text).width + 12;
    const textHeight = parseInt(ctx.font.split(" ")[1], 10) + 8;
    ctx.fillStyle = color;
    ctx.fillRect(x1, Math.max(0, y1 - textHeight), textWidth, textHeight);
    ctx.fillStyle = "#111";
    ctx.fillText(text, x1 + 6, Math.max(textHeight - 8, y1 - 8));
  }
}

export default function App() {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const api = useMemo(() => new ApiClient(settings.apiUrl), [settings.apiUrl]);
  const [model, setModel] = useState<ModelState>({ status: "loading" });
  const [mode, setMode] = useState<Mode>("idle");
  const [fix, setFix] = useState<LocationFix | null>(null);
  const [locationError, setLocationError] = useState<string | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [queue, setQueue] = useState(0);
  const [hazards, setHazards] = useState<Incident[]>([]);
  const [alert, setAlert] = useState<{ type: HazardType; distanceM: number } | null>(null);
  const [perf, setPerf] = useState<{ inferenceMs: number; fps: number } | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [benchmark, setBenchmark] = useState<BenchmarkResult | null | "running">(null);

  const detectorRef = useRef<Detector | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fixRef = useRef<LocationFix | null>(null);
  const alertedRef = useRef(new Map<string, number>());
  const wakeLockRef = useRef<{ release: () => Promise<void> } | null>(null);
  const trackerRef = useRef(new HazardTracker({ ...DETECTION, minScore: settings.minScore, minScoreByLabel: MIN_SCORE_BY_LABEL }));

  const updateSettings = (next: Settings) => {
    setSettings(next);
    saveSettings(next);
    trackerRef.current = new HazardTracker({ ...DETECTION, minScore: next.minScore, minScoreByLabel: MIN_SCORE_BY_LABEL });
  };

  // Load the model once (from the service-worker cache when offline).
  useEffect(() => {
    const detector = new Detector();
    detectorRef.current = detector;
    let active = true;
    detector
      .load()
      .then((info) => active && setModel({ status: "ready", info }))
      .catch((error) => active && setModel({ status: "error", error: String(error) }));
    return () => {
      active = false;
      detector.terminate();
    };
  }, []);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3_500);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!alert) return;
    const timer = setTimeout(() => setAlert(null), 8_000);
    return () => clearTimeout(timer);
  }, [alert]);

  // Location (GPS or simulated drive along the corridor).
  useEffect(() => {
    setFix(null);
    fixRef.current = null;
    return startLocation(
      settings.locationSource,
      { startKm: settings.routeStartKm, speedKmh: settings.routeSpeedKmh },
      (next) => {
        fixRef.current = next;
        setFix(next);
        setLocationError(null);
      },
      setLocationError,
    );
  }, [settings.locationSource, settings.routeStartKm, settings.routeSpeedKmh]);

  // Outbox: send queued reports when there is signal.
  const runSync = useCallback(async () => {
    const summary = await syncOutbox(api);
    setQueue(await pendingCount());
    if (summary.lastResult) setLastResult(describe(summary.lastResult));
  }, [api]);

  useEffect(() => {
    pendingCount().then(setQueue).catch(() => undefined);
    const tick = () => {
      if (navigator.onLine) void runSync().catch(() => undefined);
    };
    tick();
    const timer = setInterval(tick, SYNC.outboxIntervalMs);
    window.addEventListener("online", tick);
    return () => {
      clearInterval(timer);
      window.removeEventListener("online", tick);
    };
  }, [runSync]);

  // Nearby confirmed hazards: refreshed online, cached in IndexedDB for alerts without signal.
  const hasFix = fix !== null;
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      const current = fixRef.current;
      try {
        if (current && navigator.onLine) {
          const list = await api.nearby(current.point, SYNC.nearbyRadiusM);
          if (!cancelled) setHazards(list);
          await cacheHazards(list);
          return;
        }
      } catch {
        // fall back to the cache below
      }
      const cached = await cachedHazards();
      if (!cancelled && current) {
        // Distances in the cache are stale; recompute from the current position.
        setHazards(cached.map((h) => ({ ...h, distanceM: haversineM(current.point, h.location.coordinates) })));
      } else if (!cancelled) {
        setHazards(cached);
      }
    };
    void refresh();
    const timer = setInterval(refresh, SYNC.nearbyIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [api, hasFix]);

  // Voice / vibration / full-screen alerts for hazards ahead.
  useEffect(() => {
    if (!fix) return;
    const due = dueAlerts(
      hazards
        .filter((h) => h.status === "confirmed")
        .map((h) => ({ id: h.id, type: h.type, location: h.location.coordinates })),
      { point: fix.point, heading: fix.heading, speedMs: fix.speedMs },
      alertedRef.current,
      Date.now(),
      { distanceM: settings.alertDistanceM, repeatMs: ALERTS.repeatMs, headingToleranceDeg: ALERTS.headingToleranceDeg },
    );
    if (due.length === 0) return;
    const now = Date.now();
    for (const item of due) alertedRef.current.set(item.hazard.id, now);
    const nearest = due[0];
    setAlert({ type: nearest.hazard.type, distanceM: nearest.distanceM });
    if (settings.voice) speak(alertSentence(nearest.hazard.type, nearest.distanceM));
    vibrate(nearest.hazard.type);
  }, [fix, hazards, settings.voice, settings.alertDistanceM]);

  // A confirmed on-device detection becomes a queued report (photo anonymized in the worker).
  const report = useCallback(
    async (detection: Detection) => {
      const current = fixRef.current;
      const type = detection.label as HazardType;
      if (!current) {
        setToast(`${hazardLabel(type)} detectado, pero sin GPS: no se reportó.`);
        return;
      }
      const detector = detectorRef.current;
      const image = settings.sendPhotos && detector ? await detector.anonymize(detection.box) : null;
      const payload: ReportPayload = {
        clientReportId: crypto.randomUUID(),
        deviceId: deviceId(),
        type,
        confidence: Math.round(detection.score * 1000) / 1000,
        location: { type: "Point", coordinates: current.point },
        accuracyM: current.accuracyM,
        headingDeg: current.heading !== null ? current.heading % 360 : null,
        speedKmh: current.speedMs !== null ? Math.min(299, current.speedMs * 3.6) : null,
        ts: new Date().toISOString(),
        modelVersion: model.info?.meta.sha256.slice(0, 12) ?? null,
      };
      await enqueue(payload, image);
      setQueue(await pendingCount());
      setToast(`${hazardLabel(type)} detectado · reporte guardado${navigator.onLine ? "" : " (se enviará con señal)"}`);
      if (navigator.onLine) void runSync().catch(() => undefined);
    },
    [model.info, runSync, settings.sendPhotos],
  );

  // Detection loop: one frame at a time (backpressure), never blocking the UI thread.
  useEffect(() => {
    if (mode === "idle" || model.status !== "ready" || !detectorRef.current) return;
    const detector = detectorRef.current;
    let cancelled = false;
    let frames = 0;
    let windowStart = performance.now();
    let inferenceSum = 0;
    (async () => {
      while (!cancelled) {
        const video = videoRef.current;
        if (video && video.readyState >= 2 && !video.paused && video.videoWidth > 0) {
          try {
            const bitmap = await createImageBitmap(video);
            const { videoWidth, videoHeight } = video;
            const result = await detector.detect(bitmap, Math.min(0.25, settings.minScore));
            if (cancelled) break;
            if (canvasRef.current) {
              drawDetections(canvasRef.current, videoWidth, videoHeight, result.detections, result.context);
            }
            frames += 1;
            inferenceSum += result.inferenceMs;
            const elapsed = performance.now() - windowStart;
            if (elapsed > 1_000) {
              setPerf({ inferenceMs: inferenceSum / frames, fps: (frames * 1000) / elapsed });
              frames = 0;
              inferenceSum = 0;
              windowStart = performance.now();
            }
            const confirmed = trackerRef.current.update(result.detections, Date.now(), fixRef.current?.point ?? null);
            for (const detection of confirmed) await report(detection);
          } catch (error) {
            console.warn("detection failed", error);
          }
        }
        await sleep(DETECTION.intervalMs);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode, model.status, report, settings.minScore]);

  const keepScreenOn = async () => {
    try {
      const nav = navigator as Navigator & { wakeLock?: { request: (t: "screen") => Promise<{ release: () => Promise<void> }> } };
      wakeLockRef.current = (await nav.wakeLock?.request("screen")) ?? null;
    } catch {
      // not supported or denied: the app still works
    }
  };

  const stop = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    const video = videoRef.current;
    if (video) {
      video.pause();
      video.srcObject = null;
      video.removeAttribute("src");
      video.load();
    }
    canvasRef.current?.getContext("2d")?.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    void wakeLockRef.current?.release().catch(() => undefined);
    setPerf(null);
    setMode("idle");
  };

  const startCamera = async () => {
    const video = videoRef.current;
    if (!video) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      video.srcObject = stream;
      await video.play();
      setMode("camera");
      void keepScreenOn();
    } catch {
      setToast("No se pudo abrir la cámara. Revisa los permisos (requiere HTTPS).");
    }
  };

  const startDemo = async (source: string = DEMO_VIDEO_URL) => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = null;
    video.src = source;
    video.loop = true;
    video.muted = true;
    try {
      await video.play();
      setMode("demo");
      void keepScreenOn();
    } catch {
      setToast("No se pudo reproducir el video de demostración.");
    }
  };

  const runBenchmark = async () => {
    if (!detectorRef.current) return;
    setBenchmark("running");
    try {
      setBenchmark(await detectorRef.current.benchmark(20));
    } catch {
      setBenchmark(null);
    }
  };

  const ready = model.status === "ready";

  return (
    <div className="app">
      <header className="appbar">
        <div className="appbar-inner">
          <div className="brand">
            <img src="/icons/icon.svg" alt="" width={40} height={40} />
            <div>
              <h1>VíaSegura IA</h1>
              <p>Asistente de seguridad vial</p>
            </div>
          </div>
          <button className="icon-button" onClick={() => setSettingsOpen(true)} aria-label="Configuración">
            {Icons.settings}
          </button>
        </div>
        <div className="lane-marking" aria-hidden="true" />
      </header>

      <main className="content">
        <StatusBar online={online} fix={fix} locationError={locationError} queue={queue} />

        <section className={`stage ${mode === "idle" ? "idle" : "running"}`}>
          <video ref={videoRef} playsInline muted aria-label="Vista de la cámara" />
          <canvas ref={canvasRef} aria-hidden="true" />
          {mode === "idle" && (
            <div className="start">
              <div className="start-visual" aria-hidden="true">
                <svg viewBox="0 0 400 170" preserveAspectRatio="xMidYMax slice">
                  <defs>
                    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0" stopColor="#12304f" />
                      <stop offset="1" stopColor="#2a5481" />
                    </linearGradient>
                  </defs>
                  <rect width="400" height="170" fill="url(#sky)" />
                  <path d="M0 120 70 74l60 30 70-50 80 46 50-26 70 40v56H0z" fill="#0b1f36" opacity="0.55" />
                  <path d="M150 170 192 72h16l42 98z" fill="#2b3138" />
                  <path d="M199 80h2l1 12h-4zm-1 24h4l1 18h-6zm-2 32h8l2 28h-12z" fill="#f2b705" />
                  <g transform="translate(286 34)">
                    <rect x="8" y="8" width="44" height="44" rx="4" transform="rotate(45 30 30)" fill="#f2b705" stroke="#111" strokeWidth="3" />
                    <ellipse cx="30" cy="36" rx="9" ry="4.5" fill="#111" />
                  </g>
                </svg>
              </div>
              <div className="start-body">
                <span className="eyebrow">Detección en el dispositivo</span>
                <h2>Detecte baches y derrumbes mientras conduce</h2>
                <p>
                  La IA analiza la vía en el propio celular, sin enviar video. Cada peligro se reporta con su ubicación y una
                  foto anonimizada; si no hay señal, se guarda y se envía después.
                </p>
                {model.status === "loading" && <p className="model-state">Cargando el modelo de IA en el dispositivo…</p>}
                {model.status === "error" && <p className="model-state error">No se pudo cargar el modelo: {model.error}</p>}
                <div className="actions">
                  <button className="btn btn-primary" disabled={!ready} onClick={startCamera}>
                    {Icons.camera}
                    Iniciar con la cámara
                  </button>
                  <button className="btn btn-outline" disabled={!ready} onClick={() => startDemo()}>
                    {Icons.play}
                    Modo demostración
                  </button>
                  <label className={`btn btn-ghost ${ready ? "" : "disabled"}`}>
                    {Icons.film}
                    Analizar un video propio
                    <input
                      type="file"
                      accept="video/*"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) void startDemo(URL.createObjectURL(file));
                      }}
                      disabled={!ready}
                    />
                  </label>
                </div>
                <p className="hint">Monte el celular en el parabrisas, con la cámara hacia la vía.</p>
              </div>
            </div>
          )}
          {mode !== "idle" && (
            <>
              <div className="hud">
                <span className={`hud-dot ${mode}`} />
                {mode === "demo" ? "Demostración" : "Cámara en vivo"}
                <span className="hud-sep" />
                {perf ? `IA ${perf.inferenceMs.toFixed(0)} ms · ${perf.fps.toFixed(1)} cuadros/s` : "Analizando…"}
              </div>
              <button className="stop" onClick={stop}>
                Detener
              </button>
            </>
          )}
        </section>

        {lastResult && (
          <p className="result" role="status">
            {lastResult}
          </p>
        )}
        <HazardList hazards={hazards} fix={fix} />
        <p className="footnote">
          {Icons.shield}
          Privacidad: las fotos se recortan y anonimizan en el celular antes de enviarse. El identificador del dispositivo
          cambia cada día.
        </p>
      </main>

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
      <AlertOverlay alert={alert} onClose={() => setAlert(null)} />
      <SettingsSheet
        open={settingsOpen}
        settings={settings}
        onChange={updateSettings}
        onClose={() => setSettingsOpen(false)}
        model={model.info}
        benchmark={benchmark}
        onBenchmark={runBenchmark}
      />
    </div>
  );
}
