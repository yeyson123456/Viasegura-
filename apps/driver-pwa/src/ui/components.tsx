// Presentational components. Visual language: Peruvian road signage (navy + preventive yellow).
import type { ReactNode } from "react";
import type { BenchmarkResult, LoadInfo } from "../detection/detector";
import { hazardLabel } from "../lib/alerts";
import type { Incident } from "../lib/api";
import type { LocationFix } from "../lib/location";
import type { Settings } from "../lib/settings";

export function formatDistance(meters: number): string {
  if (meters < 50) return "< 50 m";
  return meters < 1000 ? `${Math.round(meters / 10) * 10} m` : `${(meters / 1000).toFixed(1)} km`;
}

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const Icons = {
  signal: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path {...stroke} d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0" />
      <circle cx="12" cy="19.5" r="1.4" fill="currentColor" />
    </svg>
  ),
  location: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path {...stroke} d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21Z" />
      <circle {...stroke} cx="12" cy="9.5" r="2.5" />
    </svg>
  ),
  upload: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path {...stroke} d="M12 15V4m0 0L7.5 8.5M12 4l4.5 4.5M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </svg>
  ),
  camera: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path {...stroke} d="M3 8a2 2 0 0 1 2-2h2.5L9 4h6l1.5 2H19a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
      <circle {...stroke} cx="12" cy="13" r="3.5" />
    </svg>
  ),
  play: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle {...stroke} cx="12" cy="12" r="9" />
      <path d="M10 8.5v7l6-3.5z" fill="currentColor" />
    </svg>
  ),
  film: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect {...stroke} x="3" y="5" width="18" height="14" rx="2" />
      <path {...stroke} d="M7 5v14M17 5v14M3 9h4m10 0h4M3 15h4m10 0h4" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path {...stroke} d="M4 7h10m4 0h2M4 17h4m4 0h8" />
      <circle {...stroke} cx="16" cy="7" r="2" />
      <circle {...stroke} cx="10" cy="17" r="2" />
    </svg>
  ),
  shield: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path {...stroke} d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6Z" />
      <path {...stroke} d="m9 12 2 2 4-4" />
    </svg>
  ),
};

/** Pictograms used inside the preventive (diamond) sign. */
function Pictogram({ type }: { type: Incident["type"] }) {
  return type === "obstacle" ? (
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <path d="M18 78h64L66 52l-9 10-15-24z" fill="#111" />
      <circle cx="70" cy="28" r="7" fill="#111" />
      <circle cx="56" cy="38" r="4.5" fill="#111" />
    </svg>
  ) : (
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <path d="M20 80 40 20h20l20 60z" fill="none" stroke="#111" strokeWidth="5" />
      <ellipse cx="50" cy="62" rx="14" ry="7" fill="#111" />
    </svg>
  );
}

export function HazardBadge({ type }: { type: Incident["type"] }) {
  return (
    <span className={`hazard-badge ${type}`} aria-hidden="true">
      <span className="diamond">
        <Pictogram type={type} />
      </span>
    </span>
  );
}

function StatusTile({ icon, label, value, tone }: { icon: ReactNode; label: string; value: string; tone: "ok" | "warn" | "neutral" }) {
  return (
    <div className={`status-tile ${tone}`}>
      <span className="status-icon">{icon}</span>
      <span className="status-text">
        <small>{label}</small>
        <strong>{value}</strong>
      </span>
    </div>
  );
}

export function StatusBar({
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
  const location = fix
    ? fix.source === "route"
      ? "Ruta simulada"
      : `GPS ± ${Math.round(fix.accuracyM ?? 0)} m`
    : locationError
      ? "Sin permiso"
      : "Buscando…";
  return (
    <div className="status-bar" role="status" aria-live="polite">
      <StatusTile icon={Icons.signal} label="Conexión" value={online ? "En línea" : "Sin señal"} tone={online ? "ok" : "warn"} />
      <StatusTile icon={Icons.location} label="Ubicación" value={location} tone={fix ? "ok" : "warn"} />
      <StatusTile
        icon={Icons.upload}
        label="Envíos"
        value={queue ? `${queue} en cola` : "Al día"}
        tone={queue ? "warn" : "neutral"}
      />
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
      <span className="alert-kicker">Peligro confirmado adelante</span>
      <span className="sign">
        <span className="sign-diamond">
          <Pictogram type={alert.type} />
        </span>
      </span>
      <strong className="alert-title">{hazardLabel(alert.type)}</strong>
      <span className="alert-distance">
        {alert.distanceM < 50 ? "muy cerca" : `a ${formatDistance(alert.distanceM)}`}
      </span>
      <span className="alert-advice">{alert.type === "obstacle" ? "Reduzca la velocidad" : "Conduzca con precaución"}</span>
      <small className="alert-dismiss">Toque la pantalla para cerrar</small>
    </button>
  );
}

export function HazardList({ hazards, fix }: { hazards: Incident[]; fix: LocationFix | null }) {
  const confirmed = hazards.filter((h) => h.status === "confirmed");
  return (
    <section className="card" aria-label="Peligros confirmados cercanos">
      <header className="card-head">
        <div>
          <h2>Peligros confirmados</h2>
          <p>En un radio de 5 km · disponibles también sin señal</p>
        </div>
        <span className="counter">{confirmed.length}</span>
      </header>
      {confirmed.length === 0 ? (
        <div className="empty">
          <span className="empty-icon">{Icons.shield}</span>
          <div>
            <strong>{fix ? "Vía despejada" : "Esperando ubicación"}</strong>
            <p>
              {fix
                ? "No hay peligros confirmados en los alrededores."
                : "Active la ubicación para recibir alertas de su ruta."}
            </p>
          </div>
        </div>
      ) : (
        <ul className="hazards">
          {confirmed.slice(0, 6).map((hazard) => (
            <li key={hazard.id}>
              <HazardBadge type={hazard.type} />
              <div className="hazard-text">
                <strong>{hazardLabel(hazard.type)}</strong>
                <span>{hazard.segmentName ?? "Fuera de tramos registrados"}</span>
              </div>
              <div className="hazard-meta">
                <strong>{hazard.distanceM != null ? formatDistance(hazard.distanceM) : "—"}</strong>
                <span>{hazard.reportsCount} reportes</span>
              </div>
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
      <div className="sheet" role="dialog" aria-label="Configuración" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>Configuración</h2>
          <button className="text-button" onClick={onClose}>
            Cerrar
          </button>
        </header>

        <fieldset>
          <legend>Conexión</legend>
          <label>
            Servidor (API)
            <input value={settings.apiUrl} onChange={(e) => set("apiUrl", e.target.value)} inputMode="url" />
          </label>
        </fieldset>

        <fieldset>
          <legend>Ubicación</legend>
          <label>
            Fuente
            <select
              value={settings.locationSource}
              onChange={(e) => set("locationSource", e.target.value as Settings["locationSource"])}
            >
              <option value="gps">GPS del celular</option>
              <option value="route">Ruta simulada Huánuco – Tingo María (demostración)</option>
            </select>
          </label>
          {settings.locationSource === "route" && (
            <div className="two">
              <label>
                Inicio (km)
                <input type="number" min={0} max={120} value={settings.routeStartKm} onChange={(e) => set("routeStartKm", Number(e.target.value))} />
              </label>
              <label>
                Velocidad (km/h)
                <input type="number" min={5} max={90} value={settings.routeSpeedKmh} onChange={(e) => set("routeSpeedKmh", Number(e.target.value))} />
              </label>
            </div>
          )}
        </fieldset>

        <fieldset>
          <legend>Alertas y detección</legend>
          <label className="check">
            <input type="checkbox" checked={settings.voice} onChange={(e) => set("voice", e.target.checked)} />
            Alertas por voz
          </label>
          <label className="check">
            <input type="checkbox" checked={settings.sendPhotos} onChange={(e) => set("sendPhotos", e.target.checked)} />
            Adjuntar foto anonimizada a cada reporte
          </label>
          <label>
            Distancia de alerta <span className="value">{settings.alertDistanceM} m</span>
            <input type="range" min={100} max={1500} step={50} value={settings.alertDistanceM} onChange={(e) => set("alertDistanceM", Number(e.target.value))} />
          </label>
          <label>
            Umbral de detección <span className="value">{Math.round(settings.minScore * 100)} %</span>
            <input type="range" min={0.2} max={0.8} step={0.05} value={settings.minScore} onChange={(e) => set("minScore", Number(e.target.value))} />
          </label>
        </fieldset>

        <fieldset>
          <legend>Modelo de IA en el dispositivo</legend>
          {model ? (
            <dl className="facts">
              <dt>Clases</dt>
              <dd>{model.meta.classes.map((c) => hazardLabel(c as Incident["type"])).join(" · ")}</dd>
              <dt>Entrada</dt>
              <dd>{model.meta.imgsz} px</dd>
              <dt>Hilos</dt>
              <dd>
                {model.threads}
                {model.isolated ? "" : " (sin aislamiento de origen)"}
              </dd>
              <dt>Versión</dt>
              <dd className="mono">{model.meta.sha256.slice(0, 12)}</dd>
            </dl>
          ) : (
            <p className="muted">Cargando modelo…</p>
          )}
          <button className="btn btn-outline" onClick={onBenchmark} disabled={!model || benchmark === "running"}>
            {benchmark === "running" ? "Midiendo…" : "Medir rendimiento (20 inferencias)"}
          </button>
          {benchmark && benchmark !== "running" && (
            <p className="bench">
              Mediana <strong>{benchmark.medianMs.toFixed(0)} ms</strong> · p90 <strong>{benchmark.p90Ms.toFixed(0)} ms</strong> ·{" "}
              {benchmark.threads} hilo(s)
            </p>
          )}
        </fieldset>
      </div>
    </div>
  );
}
