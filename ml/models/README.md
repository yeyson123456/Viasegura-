# ml/models

Deployed model artifacts, written by `ml/export_onnx.py`:

- `hazards.onnx`: two-class detector (0 = pothole, 1 = obstacle) exported from the best training run.
- `hazards.json`: metadata read by the PWA and the API (classes, input size, output layout,
  SHA-256, source weights).

The same files are copied to `apps/driver-pwa/public/models/` (phone) and baked into the API
image (server-side re-detection). Metrics for this exact file: `ml/results/`.
