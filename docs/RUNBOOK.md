# Runbook

## Install a model release

```powershell
cd backend
.venv\Scripts\python scripts\fetch_model.py --version 0.1.0-preview --source-dir ..\ml\artifacts\0.1.0-preview --out models\current
```

The script checks the SHA-256 against `models/registry/<version>.json` and installs nothing on a mismatch. In a container, set `MODEL_VERSION` and `MODEL_BASE_URL` (HTTPS approved storage holding `<version>/model.onnx`), or mount a verified folder at `/app/models/current`.

## Deploy (one container)

1. CI must be green on the commit.
2. Run the **Release** workflow with `model_version` and `channel`. `production` is refused unless the registry records a locked-test mAP@0.50 ≥ 0.85.
3. On the host, run `ghcr.io/<owner>/ecorevive:<sha>-<model_version>` with:
   - `PORT` (if the host sets it), `MODEL_VERSION`, `MODEL_BASE_URL`.
   - `GEMINI_API_KEY` as a host secret.
   - `ECOREVIVE_MODEL_STATUS=preview` until the model passes evaluation.
   - At least 1 vCPU and 1 GB RAM. One instance, because idempotency, rate limits and the guide cache are in memory.
   - HTTPS at the host's edge. Camera access in browsers requires HTTPS.
4. Smoke test: `/healthz` returns 200, `/readyz` returns 200 with the expected model version, and one real `POST /v1/detect` and one `POST /v1/guides` succeed. Then check the logs for `model_ready` and no `unhandled_error`.

**Hosting is not chosen yet.** Any container host with HTTPS and secrets works, for example Google Cloud Run, Fly.io or Render. Pick one after measuring the real model's latency and memory with `scripts/load_test.py`.

## Rollback

Redeploy the previous image tag, which encodes commit and model version, for example `abc1234-0.1.0-preview`. For a model-only rollback, set `MODEL_VERSION` to the previous registry entry and restart. Every version stays in the registry, and its checksum guarantees the exact file is restored.

## Operations

- **Health:**
  - `/healthz` shows the process is alive.
  - `/readyz` returns 200 only when the model is loaded and warmed. When it isn't, it returns 503 and the reason.
- **Metrics:** `/v1/metrics` shows request counts by status, overload and timeout counts, guide fallbacks by reason, inference p50/p95, and in-flight jobs.
- **Logs:** JSON, one line per request, with `request_id`. Images, guide hints, keys and IP addresses are never logged.
- **Busy (many 503 `overloaded`):** check inference p95 in `/v1/metrics`. Scale vertically first. Only raise `ECOREVIVE_INFERENCE_CONCURRENCY` after measuring CPU on the host.
- **Many guide fallbacks:**
  - `guide_fallback_http_429` means the Gemini quota is exhausted.
  - `guide_fallback_timeout` means Gemini is slow.
  - In both cases the app keeps working with curated guides, labelled as such.
- **Rotate the Gemini key:** update the host secret, then restart. The key never reaches the browser or the app.

## Data handling

Uploaded images live only in memory for the duration of a request and are never stored. No database is used.
