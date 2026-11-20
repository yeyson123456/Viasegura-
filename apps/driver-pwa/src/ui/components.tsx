// Presentational components (Spanish UI, large touch targets, readable while driving).
import type { BenchmarkResult, LoadInfo } from "../detection/detector";
import { hazardLabel } from "../lib/alerts";
import type { Incident } from "../lib/api";
import type { LocationFix } from "../lib/location";
import type { Settings } from "../lib/settings";

export function formatDistance(meters: number): string {
  return meters < 1000 ? `${Math.round(meters / 10) * 10} m` : `${(meters / 1000).toFixed(1)} km`;
}

function HazardIcon({ type, size = 28 }: { type: Incident["type"]; size?: number }) {
  // Distinct shapes, not only colours (colour-blind friendly).
  return type === "obstacle" ? (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2 1 21h22L12 2Z" fill="currentColor" />
      <path d="M12 9v5m0 3v.5" stroke="#111" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  ) : (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <ellipse cx="12" cy="14" rx="10" ry="6" fill="currentColor" />
      <ellipse cx="12" cy="14" rx="5.5" ry="2.8" fill="#111" />
    </svg>
  );
}

export function StatusPills({
  online,
  fix,
  locationError,
  queue,
}: {
  online: boolean;
  fix: LocationFix | null;
  locationError: string | null;
  queue: number;
}) {
  return (
    <div className="pills" role="status" aria-live="polite">
      <span className={`pill ${online ? "ok" : "warn"}`}>{online ? "● En línea" : "○ Sin señal"}</span>
      <span className={`pill ${fix ? "ok" : "warn"}`} title={locationError ?? undefined}>
        {fix
          ? fix.source === "route"
            ? "Ruta simulada"
            : `GPS ±${Math.round(fix.accuracyM ?? 0)} m`
          : "Sin GPS"}
      </span>
      <span className={`pill ${queue ? "warn" : ""}`}>{queue ? `⇪ ${queue} en cola` : "✓ Al día"}</span>
    </div>
  );
}

export function AlertOverlay({
  alert,
  onClose,
}: {
  alert: { type: Incident["type"]; distanceM: number } | null;
  onClose: () => void;
}) {
  if (!alert) return null;
  return (
    <button className={`alert-overlay ${alert.type}`} onClick={onClose} aria-live="assertive">
      <HazardIcon type={alert.type} size={120} />
      <strong>{hazardLabel(alert.type).toUpperCase()}</strong>
      <span className="alert-distance">a {formatDistance(alert.distanceM)}</span>
      <span className="alert-advice">{alert.type === "obstacle" ? "Reduzca la velocidad" : "Precaución"}</span>
      <small>Toca para cerrar</small>
    </button>
  );
}

export function HazardList({ hazards, fix }: { hazards: Incident[]; fix: LocationFix | null }) {
  const confirmed = hazards.filter((h) => h.status === "confirmed");
  return (
    <section className="panel" aria-label="Peligros cercanos">
      <h2>
        Peligros confirmados cerca <span className="count">{confirmed.length}</span>
      </h2>
      {confirmed.length === 0 ? (
        <p className="muted">
          {fix ? "No hay peligros confirmados en 5 km." : "Esperando ubicación para buscar peligros…"}
        </p>
      ) : (
        <ul className="hazards">
          {confirmed.slice(0, 6).map((hazard) => (
            <li key={hazard.id} className={hazard.type}>
              <HazardIcon type={hazard.type} />
              <div>
                <strong>{hazardLabel(hazard.type)}</strong>
                <span className="muted">
                  {hazard.distanceM != null ? formatDistance(hazard.distanceM) : ""}
                  {hazard.segmentName ? ` · ${hazard.segmentName}` : ""}
                </span>
              </div>
              <span className="badge">{hazard.reportsCount} reportes</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function SettingsSheet({
  open,
  settings,
  onChange,
  onClose,
  model,
  benchmark,
  onBenchmark,
}: {
  open: boolean;
  settings: Settings;
  onChange: (settings: Settings) => void;
  onClose: () => void;
  model: LoadInfo | undefined;
  benchmark: BenchmarkResult | null | "running";
  onBenchmark: () => void;
}) {
  if (!open) return null;
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => onChange({ ...settings, [key]: value });
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label="Ajustes" onClick={(e) => e.stopPropagation()}>
        <h2>Ajustes</h2>
        <label>
          Servidor (API)
          <input value={settings.apiUrl} onChange={(e) => set("apiUrl", e.target.value)} inputMode="url" />
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.voice} onChange={(e) => set("voice", e.target.checked)} />
          Alertas por voz
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={settings.sendPhotos}
            onChange={(e) => set("sendPhotos", e.target.checked)}
          />
          Enviar foto anonimizada con cada reporte
        </label>
        <label>
          Ubicación
          <select
            value={settings.locationSource}
            onChange={(e) => set("locationSource", e.target.value as Settings["locationSource"])}
          >
            <option value="gps">GPS del celular</option>
            <option value="route">Ruta simulada Huánuco – Tingo María (demo)</option>
          </select>
        </label>
        {settings.locationSource === "route" && (
          <div className="two">
            <label>
              Inicio (km)
              <input
                type="number"
                min={0}
                max={120}
                value={settings.routeStartKm}
                onChange={(e) => set("routeStartKm", Number(e.target.value))}
              />
            </label>
            <label>
              Velocidad (km/h)
              <input
                type="number"
                min={5}
                max={90}
                value={settings.routeSpeedKmh}
                onChange={(e) => set("routeSpeedKmh", Number(e.target.value))}
              />
            </label>
          </div>
        )}
        <label>
          Distancia de alerta: {settings.alertDistanceM} m
          <input
            type="range"
            min={100}
            max={1500}
            step={50}
            value={settings.alertDistanceM}
            onChange={(e) => set("alertDistanceM", Number(e.target.value))}
          />
        </label>
        <label>
          Umbral de detección: {Math.round(settings.minScore * 100)} %
          <input
            type="range"
            min={0.2}
            max={0.8}
            step={0.05}
            value={settings.minScore}
            onChange={(e) => set("minScore", Number(e.target.value))}
          />
        </label>
        <div className="model-info">
          <strong>Modelo en el celular</strong>
          {model ? (
            <span className="muted">
              {model.meta.classes.join(" · ")} · {model.meta.imgsz}px · {model.threads} hilo(s)
              {model.isolated ? "" : " (sin aislamiento: 1 hilo)"} · {model.meta.sha256.slice(0, 12)}
            </span>
          ) : (
            <span className="muted">Cargando…</span>
          )}
          <button className="secondary" onClick={onBenchmark} disabled={!model || benchmark === "running"}>
            {benchmark === "running" ? "Midiendo…" : "Medir rendimiento (20 inferencias)"}
          </button>
          {benchmark && benchmark !== "running" && (
            <span>
              Mediana {benchmark.medianMs.toFixed(0)} ms · p90 {benchmark.p90Ms.toFixed(0)} ms ·{" "}
              {benchmark.threads} hilo(s)
            </span>
          )}
        </div>
        <button onClick={onClose}>Listo</button>
      </div>
    </div>
  );
}
