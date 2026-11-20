# VíaSegura IA

**The driver's phone as a road sensor.** On-device computer vision detects potholes and
obstacles/landslides, reports are confirmed by consensus across independent devices, and confirmed
hazards are pushed to other drivers and to a management dashboard that ranks road segments by risk.

Prototype for the **WFEO Hackathon 2027 — Challenge 3: Smart, Digital and Data-Driven Transport**.
Pilot corridor: Huánuco – Tingo María (Peru).

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository, Docker Compose (API + MongoDB), tests | ✅ Done |
| 1 | Dataset (`pothole`, `obstacle`), training, ONNX export, evaluation | Planned |
| 2 | API endpoints, MongoDB indexes, consensus | Planned |
| 3 | Driver PWA: on-device detection, offline queue, voice alerts | Planned |
| 4 | Management dashboard (Azure Maps) | Planned |
| 5 | Privacy (face/plate blur) and risk function with equity rule | Planned |
| 6 | Azure deployment scripts | Planned |
| 7 | Documentation, measured results, demo script | Planned |

## Repository layout

```text
apps/driver-pwa      Driver PWA (React + TypeScript + Vite, ONNX Runtime Web)
apps/dashboard       Management dashboard (React + TypeScript + Azure Maps)
services/api         FastAPI service (Python 3.11, Docker)
services/functions   Azure Functions: segment risk recalculation
ml/                  Dataset preparation, training, ONNX export, evaluation
scripts/             Simulation, latency and privacy-audit scripts
infra/               Bicep templates and Azure CLI deployment
docs/                Architecture, decisions, results
```

## Quick start (local)

Prerequisite: Docker Desktop, or Docker Engine with Compose v2.

```bash
docker compose up --build
```

- API: <http://localhost:8000> — interactive docs at <http://localhost:8000/docs>
- Health: `curl http://localhost:8000/health` returns `"status": "ok"` and `"checks": {"database": "ok"}`
- MongoDB: `mongodb://localhost:27017` (bound to localhost only)

No `.env` file is needed. To change ports or settings, copy `.env.example` to `.env`.
Stop with `docker compose down` (add `-v` to also delete the local database volume).

## API development without Docker

Windows (PowerShell):

```powershell
cd services/api
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m uvicorn app.main:app --reload
```

macOS / Linux:

```bash
cd services/api
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/uvicorn app.main:app --reload
```

- Integration tests (`-m integration`) use `TEST_MONGODB_URI` (default `mongodb://localhost:27017`,
  the compose database). They are skipped when it is unreachable; `TEST_REQUIRE_MONGO=1` turns the
  skip into a failure (CI does this).
- Lint and format: `ruff check .` and `ruff format --check .`

## Configuration

Everything is configured through environment variables, documented in [`.env.example`](.env.example).
The repository contains no secrets; in Azure they will live in Key Vault (Phase 6).

| Variable | Default | Purpose |
|---|---|---|
| `API_ENV` | `local` | Environment name reported by `/health` |
| `API_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `API_CORS_ORIGINS` | `http://localhost:5173,http://localhost:5174` | Comma-separated allowed origins |
| `API_PORT` | `8000` | Host port of the API (compose) |
| `MONGODB_URI` | `mongodb://localhost:27017` | Used when running outside compose; compose always uses `mongodb://mongo:27017` |
| `MONGODB_DB` | `viasegura` | Database name |
| `MONGODB_TIMEOUT_MS` | `3000` | Server-selection and connect timeout |
| `MONGO_PORT` | `27017` | Host port of the local MongoDB container |

## API conventions

- **Errors** always have the shape `{"error": {"code", "message", "request_id", "details"?}}`;
  unexpected errors return a generic message and the details go to the logs only.
- **Request ids:** every response carries `X-Request-ID`. A caller-supplied id is reused when it
  matches `[A-Za-z0-9._-]{1,64}`; otherwise a new one is generated.
- **Logs:** one JSON object per line on stdout, including `request_id`, `status` and `duration_ms`.
- **Health:** `GET /health` is a readiness check (pings MongoDB, returns 503 when degraded);
  `GET /health/live` is a liveness check with no dependencies.

## Design decisions

Changes with respect to the original brief are recorded in [`docs/decisions.md`](docs/decisions.md),
for example the PyMongo Async API instead of the deprecated Motor driver, and Azure Functions on
the Flex Consumption plan.

## Known limitations (current phase)

- Only the health endpoints exist; the domain endpoints arrive in Phase 2.
- The CI workflow (`.github/workflows/ci.yml`) has not run yet because the repository is not on
  GitHub.
- No licence file yet. Ultralytics YOLO (used from Phase 1) is AGPL-3.0, so the source code must be
  published; AGPL-3.0 for the whole repository is the simplest compliant choice.
