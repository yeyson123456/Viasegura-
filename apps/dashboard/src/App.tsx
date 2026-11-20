import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  type GeoJSONSource,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";

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

function basemap(): StyleSpecification {
  const tiles = AZURE_MAPS_KEY
    ? [
        `https://atlas.microsoft.com/map/tile?api-version=2024-04-01&tilesetId=microsoft.base.road&zoom={z}&x={x}&y={y}&tileSize=256&subscription-key=${AZURE_MAPS_KEY}`,
      ]
    : ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"];
  return {
    version: 8,
    sources: {
      base: {
        type: "raster",
        tiles,
        tileSize: 256,
        attribution: AZURE_MAPS_KEY ? "© Microsoft Azure Maps" : "© OpenStreetMap contributors",
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

function riskColor(score: number): string {
  if (score >= 60) return "#ff4d4f";
  if (score >= 30) return "#ffb020";
  if (score > 0) return "#ffe066";
  return "#3ddc97";
}

function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "ahora";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`;
}

export default function App() {
  const mapRef = useRef<MapLibreMap | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [selected, setSelected] = useState<Incident | null>(null);
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
      setError(`No se pudo conectar con la API (${API_URL}): ${String(e)}`);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  // Map with risk-coloured segments, heat map and incident markers.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new MapLibreMap({
      container: containerRef.current,
      style: basemap(),
      center: [-76.12, -9.62],
      zoom: 9,
    });
    map.addControl(new NavigationControl(), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }));
    map.on("load", () => {
      map.addSource("segments", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("incidents", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "segments-casing",
        type: "line",
        source: "segments",
        paint: { "line-color": "#0b1220", "line-width": 9, "line-opacity": 0.8 },
      });
      map.addLayer({
        id: "segments",
        type: "line",
        source: "segments",
        paint: {
          "line-width": 5,
          "line-color": ["interpolate", ["linear"], ["get", "risk"], 0, "#3ddc97", 15, "#ffe066", 35, "#ffb020", 60, "#ff4d4f"],
        },
      });
      map.addLayer({
        id: "incidents-heat",
        type: "heatmap",
        source: "incidents",
        filter: ["!=", ["get", "status"], "resolved"],
        paint: {
          "heatmap-weight": ["min", 1, ["/", ["get", "reports"], 5]],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 8, 18, 14, 40],
          "heatmap-opacity": 0.65,
        },
      });
      map.addLayer({
        id: "incidents",
        type: "circle",
        source: "incidents",
        filter: ["!=", ["get", "status"], "resolved"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 5, 15, 11],
          "circle-color": ["match", ["get", "type"], "obstacle", "#ff4d4f", "#ffb020"],
          "circle-opacity": ["match", ["get", "status"], "confirmed", 1, 0.45],
          "circle-stroke-width": 2,
          "circle-stroke-color": ["match", ["get", "status"], "confirmed", "#111", "#ffffff"],
        },
      });
      map.on("click", "incidents", (event: MapLayerMouseEvent) => {
        const id = event.features?.[0]?.properties?.id as string | undefined;
        if (id) setSelected((current) => (current?.id === id ? current : { id } as Incident));
      });
      map.on("mouseenter", "incidents", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "incidents", () => (map.getCanvas().style.cursor = ""));
      void load();
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [load]);

  // Push data into the map sources.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    (map.getSource("segments") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: segments.map((s) => ({
        type: "Feature",
        geometry: s.geometry,
        properties: { risk: s.riskScore, name: s.name },
      })),
    });
    (map.getSource("incidents") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: incidents.map((i) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: i.location.coordinates },
        properties: { id: i.id, type: i.type, status: i.status, reports: i.reportsCount },
      })),
    });
  }, [segments, incidents]);

  // Keep the selected incident fresh after each refresh.
  const selectedIncident = selected ? incidents.find((i) => i.id === selected.id) ?? null : null;

  const flyTo = (incident: Incident) => {
    setSelected(incident);
    mapRef.current?.flyTo({ center: incident.location.coordinates, zoom: 15 });
  };

  const resolve = async (incident: Incident) => {
    let key = sessionStorage.getItem("viasegura.adminKey");
    if (!key) {
      key = window.prompt("Clave de administrador (X-Admin-Key) para marcar como resuelto:");
      if (!key) return;
    }
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/incidents/${incident.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-Admin-Key": key },
        body: JSON.stringify({ status: "resolved", note: "Marcado como resuelto desde el panel" }),
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
      window.alert(`No se pudo actualizar: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const open = incidents.filter((i) => i.status !== "resolved");
  const top = [...segments].sort((a, b) => b.riskScore - a.riskScore).slice(0, 10);

  return (
    <div className="layout">
      <header>
        <div>
          <h1>VíaSegura IA · Panel de gestión vial</h1>
          <p className="muted">Corredor Huánuco – Tingo María · actualiza cada 10 s</p>
        </div>
        <div className={`api ${error ? "down" : "up"}`}>
          {error ? "API sin conexión" : `En vivo · ${updatedAt?.toLocaleTimeString("es-PE") ?? "…"}`}
        </div>
      </header>
      {error && <div className="banner">{error}</div>}

      <section className="kpis">
        <div className="kpi">
          <span>Baches confirmados</span>
          <strong className="pothole">{stats?.confirmedByType.pothole ?? "–"}</strong>
        </div>
        <div className="kpi">
          <span>Obstáculos / derrumbes</span>
          <strong className="obstacle">{stats?.confirmedByType.obstacle ?? "–"}</strong>
        </div>
        <div className="kpi">
          <span>Pendientes de consenso</span>
          <strong>{stats?.incidentsByStatus.pending ?? "–"}</strong>
        </div>
        <div className="kpi">
          <span>Reportes (24 h)</span>
          <strong>{stats?.reportsLast24h ?? "–"}</strong>
        </div>
        <div className="kpi">
          <span>Regla de consenso</span>
          <strong className="small">
            {stats ? `${stats.consensus.minDevices} disp. · ${stats.consensus.radiusM} m · ${stats.consensus.windowMin} min` : "–"}
          </strong>
        </div>
      </section>

      <main>
        <div className="map-wrap">
          <div ref={containerRef} className="map" />
          <div className="legend">
            <span>
              <i style={{ background: "#ffb020" }} /> Bache
            </span>
            <span>
              <i style={{ background: "#ff4d4f" }} /> Obstáculo
            </span>
            <span>
              <i className="hollow" /> Pendiente
            </span>
            <span className="gradient">Riesgo del tramo: bajo → alto</span>
          </div>
          {selectedIncident && (
            <div className="detail">
              <button className="close" onClick={() => setSelected(null)} aria-label="Cerrar">
                ×
              </button>
              <h3>
                {LABEL[selectedIncident.type]} · <span className={`status ${selectedIncident.status}`}>{STATUS[selectedIncident.status]}</span>
              </h3>
              {selectedIncident.imageUrl && (
                <img src={`${API_URL}${selectedIncident.imageUrl}`} alt="Foto anonimizada del peligro" />
              )}
              <p className="muted">
                {selectedIncident.reportsCount} reportes de {selectedIncident.devicesCount} dispositivos · confianza máx.{" "}
                {Math.round(selectedIncident.maxConfidence * 100)} %
              </p>
              <p className="muted">
                {selectedIncident.segmentName ?? "Fuera de tramos registrados"} · visto {timeAgo(selectedIncident.lastSeen)}
              </p>
              {selectedIncident.status !== "resolved" && (
                <button disabled={busy} onClick={() => resolve(selectedIncident)}>
                  Marcar como resuelto
                </button>
              )}
            </div>
          )}
        </div>

        <aside>
          <section className="card">
            <h2>Top 10 tramos de mayor riesgo</h2>
            <table>
              <thead>
                <tr>
                  <th>Tramo</th>
                  <th>Riesgo</th>
                  <th title="Incidentes confirmados abiertos">Inc.</th>
                  <th title="Multiplicador de equidad por aislamiento">Equidad</th>
                </tr>
              </thead>
              <tbody>
                {top.map((s) => (
                  <tr key={s.id} title={`Población atendida (INEI 2017): ${s.populationServed.toLocaleString("es-PE")}`}>
                    <td>
                      {s.name}
                      <small className="muted">
                        {s.riskBreakdown?.rain72hMm != null ? ` · lluvia 72 h: ${s.riskBreakdown.rain72hMm} mm` : ""}
                      </small>
                    </td>
                    <td>
                      <div className="bar">
                        <div style={{ width: `${Math.min(100, s.riskScore)}%`, background: riskColor(s.riskScore) }} />
                        <span>{s.riskScore.toFixed(1)}</span>
                      </div>
                    </td>
                    <td>{s.openIncidents}</td>
                    <td>×{(s.riskBreakdown?.equityMultiplier ?? 1 + 0.5 * s.isolationIndex).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">
              Riesgo = 60 % incidentes + 25 % lluvia (72 h) + 15 % historial, × equidad (hasta +50 % para tramos
              aislados). El tráfico no reduce la prioridad.
            </p>
          </section>

          <section className="card">
            <h2>Incidentes activos ({open.length})</h2>
            <ul className="incidents">
              {open.slice(0, 40).map((i) => (
                <li key={i.id} onClick={() => flyTo(i)} className={i.type}>
                  <strong>{LABEL[i.type]}</strong>
                  <span className={`status ${i.status}`}>{STATUS[i.status]}</span>
                  <small className="muted">
                    {i.segmentName ?? "—"} · {i.reportsCount} rep. · {timeAgo(i.lastSeen)}
                  </small>
                </li>
              ))}
              {open.length === 0 && <li className="muted">Sin incidentes activos.</li>}
            </ul>
          </section>
        </aside>
      </main>
    </div>
  );
}
