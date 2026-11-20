import {
  LngLatBounds,
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  type GeoJSONSource,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

const API_URL: string = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const AZURE_MAPS_KEY: string | undefined = import.meta.env.VITE_AZURE_MAPS_KEY;
const REFRESH_MS = 10_000;

type HazardType = "pothole" | "obstacle";
type Status = "pending" | "confirmed" | "resolved";

interface Incident {
  id: string;
  type: HazardType;
  status: Status;
  location: { coordinates: [number, number] };
  reportsCount: number;
  devicesCount: number;
  maxConfidence: number;
  firstSeen: string;
  lastSeen: string;
  imageUrl: string | null;
  segmentName: string | null;
}

interface Segment {
  id: string;
  code: string;
  name: string;
  geometry: { type: "LineString"; coordinates: [number, number][] };
  lengthKm: number;
  riskScore: number;
  riskBreakdown: {
    terms: { incidents: number; rain: number; history: number };
    equityMultiplier: number;
    rain72hMm: number | null;
    confirmedIncidents: number;
  } | null;
  populationServed: number;
  isolationIndex: number;
  openIncidents: number;
}

interface Stats {
  reportsLast24h: number;
  incidentsByStatus: Record<Status, number>;
  confirmedByType: Record<HazardType, number>;
  lastRiskUpdate: string | null;
  consensus: { minDevices: number; radiusM: number; windowMin: number };
}

const LABEL: Record<HazardType, string> = { pothole: "Bache", obstacle: "Obstáculo / derrumbe" };
const STATUS: Record<Status, string> = { pending: "Pendiente", confirmed: "Confirmado", resolved: "Resuelto" };
const RISK_STOPS: [number, string][] = [
  [0, "#2f7d5b"],
  [15, "#9bb33c"],
  [30, "#e2a400"],
  [55, "#cf5a1d"],
  [75, "#9d1f1f"],
];

function basemap(): StyleSpecification {
  const azure = Boolean(AZURE_MAPS_KEY);
  return {
    version: 8,
    sources: {
      base: {
        type: "raster",
        tiles: azure
          ? [
              `https://atlas.microsoft.com/map/tile?api-version=2024-04-01&tilesetId=microsoft.base.road&zoom={z}&x={x}&y={y}&tileSize=256&subscription-key=${AZURE_MAPS_KEY}`,
            ]
          : ["a", "b", "c", "d"].map((s) => `https://${s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png`),
        tileSize: 256,
        attribution: azure ? "© Microsoft Azure Maps" : "© OpenStreetMap contributors · © CARTO",
      },
    },
    layers: [{ id: "base", type: "raster", source: "base" }],
  };
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

function riskLevel(score: number): { label: string; color: string } {
  if (score >= 75) return { label: "Crítico", color: "#9d1f1f" };
  if (score >= 55) return { label: "Alto", color: "#cf5a1d" };
  if (score >= 30) return { label: "Medio", color: "#e2a400" };
  if (score >= 15) return { label: "Moderado", color: "#9bb33c" };
  return { label: "Bajo", color: "#2f7d5b" };
}

function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "hace instantes";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`;
}

/** "Tramo 06 · km 50–60 · Chinchao" -> { km: "km 50–60", place: "Chinchao" } */
function splitName(name: string): { km: string; place: string } {
  const parts = name.split("·").map((p) => p.trim());
  return { km: parts[1] ?? "", place: parts[2] ?? parts[0] ?? name };
}

const Icon = {
  pothole: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <ellipse cx="12" cy="13" rx="9" ry="5" fill="none" stroke="currentColor" strokeWidth="2" />
      <ellipse cx="12" cy="13" rx="4" ry="2" fill="currentColor" />
    </svg>
  ),
  obstacle: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 19h18l-4.5-7-3 3.5L10 9z" fill="currentColor" />
      <circle cx="17" cy="6" r="2" fill="currentColor" />
    </svg>
  ),
  pending: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M12 7v5l3 2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  ),
  reports: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 20V10m6 10V4m6 16v-7m4 7H2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  ),
  consensus: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="7" cy="9" r="3" fill="none" stroke="currentColor" strokeWidth="2" />
      <circle cx="17" cy="9" r="3" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M2 20c.8-3 2.6-5 5-5s4.2 2 5 5m0 0c.8-3 2.6-5 5-5s4.2 2 5 5" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  ),
};

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 48 48" aria-hidden="true">
      <rect x="9" y="9" width="30" height="30" rx="3" transform="rotate(45 24 24)" fill="#f2b705" stroke="#0b1f36" strokeWidth="2.5" />
      <path d="M21 33l2-17h2l2 17z" fill="#0b1f36" />
      <path d="M23.6 19h.8v3h-.8zm0 5h.8v3h-.8z" fill="#f2b705" />
    </svg>
  );
}

function Kpi({ icon, label, value, note, tone }: { icon: ReactNode; label: string; value: ReactNode; note: string; tone?: string }) {
  return (
    <article className={`kpi ${tone ?? ""}`}>
      <div className="kpi-icon">{icon}</div>
      <div>
        <span className="kpi-label">{label}</span>
        <strong className="kpi-value">{value}</strong>
        <span className="kpi-note">{note}</span>
      </div>
    </article>
  );
}

export default function App() {
  const mapRef = useRef<MapLibreMap | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const fittedRef = useRef(false);
  const [mapReady, setMapReady] = useState(false);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [incidentList, segmentList, statsData] = await Promise.all([
        getJson<Incident[]>("/incidents?limit=1000"),
        getJson<Segment[]>("/segments/risk?limit=500"),
        getJson<Stats>("/stats"),
      ]);
      setIncidents(incidentList);
      setSegments(segmentList);
      setStats(statsData);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError(`No se pudo conectar con la API (${API_URL}). ${String(e)}`);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new MapLibreMap({
      container: containerRef.current,
      style: basemap(),
      center: [-76.12, -9.62],
      zoom: 9,
      attributionControl: { compact: true },
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");
    map.on("load", () => {
      map.addSource("segments", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("incidents", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "segments-casing",
        type: "line",
        source: "segments",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": 10 },
      });
      map.addLayer({
        id: "segments",
        type: "line",
        source: "segments",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-width": 6,
          "line-color": ["interpolate", ["linear"], ["get", "risk"], ...RISK_STOPS.flat()] as never,
        },
      });
      map.addLayer({
        id: "incidents-heat",
        type: "heatmap",
        source: "incidents",
        filter: ["!=", ["get", "status"], "resolved"],
        paint: {
          "heatmap-weight": ["min", 1, ["/", ["get", "reports"], 4]],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 8, 22, 15, 48],
          "heatmap-opacity": 0.55,
          "heatmap-color": [
            "interpolate",
            ["linear"],
            ["heatmap-density"],
            0,
            "rgba(242,183,5,0)",
            0.4,
            "rgba(242,183,5,0.55)",
            0.8,
            "rgba(207,90,29,0.75)",
            1,
            "rgba(157,31,31,0.9)",
          ],
        },
      });
      map.addLayer({
        id: "incidents",
        type: "circle",
        source: "incidents",
        filter: ["!=", ["get", "status"], "resolved"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 6, 15, 12],
          "circle-color": ["match", ["get", "type"], "obstacle", "#9d1f1f", "#e2a400"],
          "circle-opacity": ["match", ["get", "status"], "confirmed", 1, 0.55],
          "circle-stroke-width": ["match", ["get", "status"], "confirmed", 2.5, 2],
          "circle-stroke-color": ["match", ["get", "status"], "confirmed", "#0b1f36", "#ffffff"],
        },
      });
      map.on("click", "incidents", (event: MapLayerMouseEvent) => {
        const id = event.features?.[0]?.properties?.id as string | undefined;
        if (id) setSelectedId(id);
      });
      map.on("mouseenter", "incidents", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "incidents", () => (map.getCanvas().style.cursor = ""));
      setMapReady(true);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      fittedRef.current = false;
      setMapReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    (map.getSource("segments") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: segments.map((s) => ({ type: "Feature", geometry: s.geometry, properties: { risk: s.riskScore } })),
    });
    (map.getSource("incidents") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: incidents.map((i) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: i.location.coordinates },
        properties: { id: i.id, type: i.type, status: i.status, reports: i.reportsCount },
      })),
    });
    if (!fittedRef.current && segments.length > 0) {
      const bounds = new LngLatBounds();
      segments.forEach((s) => s.geometry.coordinates.forEach((c) => bounds.extend(c)));
      map.fitBounds(bounds, { padding: { top: 48, bottom: 48, left: 48, right: 48 }, duration: 0 });
      fittedRef.current = true;
    }
  }, [segments, incidents, mapReady]);

  const selected = selectedId ? incidents.find((i) => i.id === selectedId) ?? null : null;

  const focus = (incident: Incident) => {
    setSelectedId(incident.id);
    mapRef.current?.flyTo({ center: incident.location.coordinates, zoom: 14, duration: 900 });
  };

  const resolve = async (incident: Incident) => {
    let key = sessionStorage.getItem("viasegura.adminKey");
    if (!key) {
      key = window.prompt("Clave de administrador (X-Admin-Key) para marcar el incidente como resuelto:");
      if (!key) return;
    }
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/incidents/${incident.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-Admin-Key": key },
        body: JSON.stringify({ status: "resolved", note: "Atendido por la cuadrilla de mantenimiento" }),
      });
      if (response.status === 401) {
        sessionStorage.removeItem("viasegura.adminKey");
        window.alert("Clave de administrador incorrecta.");
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      sessionStorage.setItem("viasegura.adminKey", key);
      await load();
    } catch (e) {
      window.alert(`No se pudo actualizar el incidente: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const open = incidents.filter((i) => i.status !== "resolved");
  const top = [...segments].sort((a, b) => b.riskScore - a.riskScore).slice(0, 10);
  const totalKm = segments.reduce((sum, s) => sum + s.lengthKm, 0);

  return (
    <div className="page">
      <header className="masthead">
        <div className="masthead-inner">
          <div className="brand">
            <Logo />
            <div>
              <h1>VíaSegura IA</h1>
              <p>Sistema de Gestión de Riesgo Vial</p>
            </div>
          </div>
          <div className="corridor">
            <span className="eyebrow">Corredor piloto</span>
            <strong>Huánuco – Tingo María</strong>
            <span className="mono">
              {segments.length} tramos · {totalKm.toFixed(1)} km
            </span>
          </div>
          <div className={`live ${error ? "down" : ""}`}>
            <span className="dot" />
            <div>
              <strong>{error ? "Sin conexión" : "En vivo"}</strong>
              <span>{updatedAt ? `Actualizado ${updatedAt.toLocaleTimeString("es-PE")}` : "Conectando…"}</span>
            </div>
          </div>
        </div>
        <div className="lane-marking" aria-hidden="true" />
      </header>

      <main className="content">
        {error && <div className="alert-banner">{error}</div>}

        <section className="kpis" aria-label="Indicadores">
          <Kpi icon={Icon.pothole} label="Baches confirmados" value={stats?.confirmedByType.pothole ?? "—"} note="Activos en el corredor" tone="amber" />
          <Kpi icon={Icon.obstacle} label="Obstáculos y derrumbes" value={stats?.confirmedByType.obstacle ?? "—"} note="Activos en el corredor" tone="red" />
          <Kpi icon={Icon.pending} label="En validación" value={stats?.incidentsByStatus.pending ?? "—"} note="Esperando consenso" />
          <Kpi icon={Icon.reports} label="Reportes · 24 h" value={stats?.reportsLast24h ?? "—"} note="Enviados por conductores" />
          <Kpi
            icon={Icon.consensus}
            label="Regla de consenso"
            value={stats ? `${stats.consensus.minDevices} · ${stats.consensus.radiusM} m · ${stats.consensus.windowMin} min` : "—"}
            note="Dispositivos · radio · ventana"
            tone="compact"
          />
        </section>

        <section className="workspace">
          <div className="panel map-panel">
            <div className="panel-head">
              <div>
                <h2>Mapa operativo</h2>
                <p>Riesgo por tramo, incidentes y concentración de reportes</p>
              </div>
            </div>
            <div className="map-frame">
              <div ref={containerRef} className="map" />
              <div className="legend">
                <span className="legend-title">Nivel de riesgo del tramo</span>
                <div className="scale">
                  {RISK_STOPS.map(([value, color]) => (
                    <i key={value} style={{ background: color }} />
                  ))}
                </div>
                <div className="scale-labels">
                  <span>Bajo</span>
                  <span>Medio</span>
                  <span>Crítico</span>
                </div>
                <div className="legend-items">
                  <span>
                    <b className="mk amber" /> Bache
                  </span>
                  <span>
                    <b className="mk red" /> Obstáculo
                  </span>
                  <span>
                    <b className="mk hollow" /> En validación
                  </span>
                </div>
              </div>
              {selected && (
                <aside className="detail">
                  <button className="detail-close" onClick={() => setSelectedId(null)} aria-label="Cerrar">
                    ×
                  </button>
                  <span className={`tag ${selected.type}`}>{LABEL[selected.type]}</span>
                  <h3>{selected.segmentName ? splitName(selected.segmentName).place : "Fuera de tramos registrados"}</h3>
                  {selected.segmentName && <span className="mono muted">{splitName(selected.segmentName).km}</span>}
                  {selected.imageUrl && (
                    <figure>
                      <img src={`${API_URL}${selected.imageUrl}`} alt="Fotografía anonimizada del peligro" />
                      <figcaption>Imagen anonimizada en el dispositivo</figcaption>
                    </figure>
                  )}
                  <dl>
                    <dt>Estado</dt>
                    <dd>
                      <span className={`status ${selected.status}`}>{STATUS[selected.status]}</span>
                    </dd>
                    <dt>Reportes</dt>
                    <dd>
                      {selected.reportsCount} de {selected.devicesCount} dispositivo(s)
                    </dd>
                    <dt>Confianza máx.</dt>
                    <dd>{Math.round(selected.maxConfidence * 100)} %</dd>
                    <dt>Último reporte</dt>
                    <dd>{timeAgo(selected.lastSeen)}</dd>
                    <dt>Coordenadas</dt>
                    <dd className="mono">
                      {selected.location.coordinates[1].toFixed(5)}, {selected.location.coordinates[0].toFixed(5)}
                    </dd>
                  </dl>
                  {selected.status !== "resolved" && (
                    <button className="btn-primary" disabled={busy} onClick={() => resolve(selected)}>
                      Marcar como resuelto
                    </button>
                  )}
                </aside>
              )}
            </div>
          </div>

          <div className="side">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Priorización de tramos</h2>
                  <p>Los 10 tramos con mayor índice de riesgo</p>
                </div>
              </div>
              <table className="ranking">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Tramo</th>
                    <th className="num">Riesgo</th>
                    <th className="num" title="Incidentes confirmados abiertos">Inc.</th>
                    <th className="num" title="Multiplicador de equidad por aislamiento">Equidad</th>
                  </tr>
                </thead>
                <tbody>
                  {top.map((s, index) => {
                    const { km, place } = splitName(s.name);
                    const level = riskLevel(s.riskScore);
                    return (
                      <tr key={s.id} title={`Población del distrito (INEI 2017): ${s.populationServed.toLocaleString("es-PE")} hab.`}>
                        <td className="rank">{String(index + 1).padStart(2, "0")}</td>
                        <td>
                          <div className="seg">
                            <span className="hito">{km.replace("km ", "")}</span>
                            <div>
                              <strong>{place}</strong>
                              <small>
                                {s.riskBreakdown?.rain72hMm != null ? `Lluvia 72 h: ${s.riskBreakdown.rain72hMm} mm` : "Sin dato de lluvia"}
                              </small>
                            </div>
                          </div>
                        </td>
                        <td className="num">
                          <div className="risk">
                            <span className="risk-value" style={{ color: level.color }}>
                              {s.riskScore.toFixed(1)}
                            </span>
                            <span className="risk-track">
                              <span style={{ width: `${Math.min(100, s.riskScore)}%`, background: level.color }} />
                            </span>
                            <span className="risk-label">{level.label}</span>
                          </div>
                        </td>
                        <td className="num mono">{s.openIncidents}</td>
                        <td className="num mono">×{(s.riskBreakdown?.equityMultiplier ?? 1 + 0.5 * s.isolationIndex).toFixed(2)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="method">
                <strong>Índice de riesgo</strong> = 60 % incidentes confirmados + 25 % lluvia acumulada 72 h + 15 % historial,
                multiplicado por un factor de equidad de hasta ×1,50 para tramos que atienden a población aislada. El volumen de
                tráfico no reduce la prioridad.
              </p>
            </section>

            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Incidentes activos</h2>
                  <p>{open.length} registro(s) · seleccione uno para ubicarlo</p>
                </div>
              </div>
              <ul className="incident-list">
                {open.slice(0, 40).map((i) => (
                  <li key={i.id}>
                    <button onClick={() => focus(i)} className={selectedId === i.id ? "active" : ""}>
                      <span className={`incident-icon ${i.type}`}>{Icon[i.type]}</span>
                      <span className="incident-text">
                        <strong>{LABEL[i.type]}</strong>
                        <small>
                          {i.segmentName ? `${splitName(i.segmentName).place} · ${splitName(i.segmentName).km}` : "Sin tramo"} ·{" "}
                          {timeAgo(i.lastSeen)}
                        </small>
                      </span>
                      <span className={`status ${i.status}`}>{STATUS[i.status]}</span>
                    </button>
                  </li>
                ))}
                {open.length === 0 && <li className="empty">No hay incidentes activos en el corredor.</li>}
              </ul>
            </section>
          </div>
        </section>
      </main>

      <footer className="footer">
        <span>VíaSegura IA · Prototipo WFEO Hackathon 2027 · Desafío 3</span>
        <span>Fuentes: OpenStreetMap (ODbL) · INEI Censo 2017 · Open-Meteo · RDD2022 · TerrainSense</span>
      </footer>
    </div>
  );
}
