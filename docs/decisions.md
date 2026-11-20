# Architecture decisions

Short log of decisions that refine or deviate from the original brief (`CLAUDE.md`).
Each entry records the context, the decision and its consequences.

## D-001 · PyMongo Async API instead of Motor (2026-11-20)

- **Context:** the brief asks for Motor as the asynchronous MongoDB driver. MongoDB deprecated
  Motor on 2025-05-14 in favour of the PyMongo Async API; Motor only receives critical fixes
  until 2027-05-14.
- **Decision:** use `pymongo.AsyncMongoClient`, the official successor (same asyncio model).
- **Consequences:** no dependency on a deprecated package.

## D-002 · Azure Functions on the Flex Consumption plan (2026-11-20)

- **Context:** the brief asks for the Consumption plan. Python functions run on Linux, and the
  Linux Consumption plan retires on 2028-09-30.
- **Decision:** host the risk function on Flex Consumption (serverless, pay-per-use).
- **Consequences:** regional availability of Flex Consumption is checked in Phase 6.

## D-003 · YOLO26n as primary detector, YOLO11n as fallback (2026-11-20)

- **Context:** the brief asks for a nano Ultralytics model exported to ONNX and run in the browser.
- **Decision:** train YOLO26n (NMS-free end-to-end head, so less post-processing on the phone) and
  keep YOLO11n as a fallback. The final choice comes from `ml/evaluate.py` and the latency script,
  never from vendor claims.
- **Consequences:** Ultralytics is AGPL-3.0, so this repository is published as open source.

## D-004 · Separate data source for the `obstacle` class (2026-11-20)

- **Context:** RDD2022 labels cracks (D00, D10, D20) and potholes (D40) but has no obstacle or
  landslide class.
- **Decision:** `pothole` comes from RDD2022 D40; `obstacle` comes from an openly licensed dataset
  plus the team's own photos of the Huánuco–Tingo María road.
- **Consequences:** obstacle metrics depend on how much data is available; `evaluate.py` reports
  per-class results as they are.

## D-005 · Data-model and endpoint additions (2026-11-20)

- `segments` gains `isolationIndex` (equity rule) and `riskBreakdown` (explainable score).
- The API gains `GET /incidents` (dashboard, any status) and `PATCH /incidents/{id}`
  (mark as resolved, protected by an admin key).

## D-006 · Offline hazard cache in the driver PWA (2026-11-20)

- While online, the PWA caches confirmed hazards around the route so voice alerts still fire in
  coverage gaps.

## D-007 · Workflow (2026-11-20)

- One git branch per phase (`phase-N-*`), merged into `main` after the phase is reviewed.
- No secrets in the repository: configuration comes from environment variables (`.env.example`).
