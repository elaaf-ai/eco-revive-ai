# Runbook

## Live deployment (Vercel, free Hobby plan)

- **Production URL:** https://ecorevive-ai.vercel.app (project `ecorevive`).
- **Setup:** the whole FastAPI app runs as one Vercel Function, with the website and the ONNX model bundled in.
  - Settings: `ECOREVIVE_ENABLED_CLASSES=["Plastic"]`, `ECOREVIVE_MODEL_STATUS=preview`, `ECOREVIVE_ONNX_THREADS=1`.
  - The Gemini key is a runtime variable of the deployment.
- **Redeploy:** create a token at https://vercel.com/account/tokens, then run:
  `$env:VERCEL_TOKEN="<token>"; backend\.venv\Scripts\python deploy\deploy_vercel.py`
  The script verifies the model checksum, builds the site, deploys, and smoke-tests the live URL.
- **Smoke test only:** `backend\.venv\Scripts\python deploy\deploy_vercel.py --smoke-only https://ecorevive-ai.vercel.app`
- **Rollback:** in the Vercel dashboard, open **Deployments**, pick the previous one, and choose **Promote to Production**. Or run `npx vercel@66.2.0 rollback --token <token>`.
- **Measured on 2026-11-19:**
  - readiness 0.87 s including a cold start
  - scan about 1.1 s
  - search guide from Gemini OK
  - non-plastic guides refused (422)
- **Limits on the free plan:**
  - The first request after a quiet period starts a new instance, which adds about 1 second.
  - In-memory rate limits and idempotency apply per instance.
- **Not free:** Hugging Face Docker Spaces now require a PRO subscription, so they are not used.

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

Uploaded images live only in memory for the duration of a request and are never stored.

### Scan history database

- **What is stored:** for each captured or uploaded scan: time (UTC), model version, quality status, number of plastic items, and each item's class and confidence. No photos, no boxes, no IP addresses. The browser's anonymous id is stored only as a SHA-256 hash. Each browser keeps at most 200 scans; users can delete theirs on the History page (`DELETE /v1/history`).
- **Where:** Neon Postgres, added to the Vercel project from **Storage → Neon**. Vercel sets `DATABASE_URL`; the app also accepts `ECOREVIVE_DATABASE_URL` or `POSTGRES_URL`. The table is created on first use.
- **Locally:** set `ECOREVIVE_DATABASE_URL=sqlite:///data/ecorevive.db` in `backend/.env`. Leave it unset to turn history off; scanning still works and the History link is hidden.
- **Outage:** scans still succeed with `scan_id: null`; `/v1/history` returns `503 history_unavailable`. Metrics: `history_saved`, `history_save_failed`.

### Feedback and training photos (adaptive learning)

- `POST /v1/feedback` stores whether a detected item was right. A photo is stored **only** when the user ticked "Share this photo"; it is re-encoded on the server, so EXIF metadata such as GPS is dropped.
- Table `feedback` in the same database. Clearing history deletes that browser's feedback and photos too.
- Export for training: `ml/scripts/export_feedback.py` (see docs/ADAPTIVE_LEARNING.md). Treat exported photos as personal data: keep them in the team's approved storage, not in Git.
- Metrics: `feedback_correct`, `feedback_wrong`, `vision_boxes_labelled`, `vision_boxes_removed`.

### Gemini vision check

- Used for captures and uploads (`?verify=true`) and for item names in guides. Live preview frames never call Gemini.
- Metrics: `vision_plastic`, `vision_no_plastic`, `vision_identified`, `vision_error_<reason>`. `vision_error_http_429` means the free quota is used up; the detector then decides alone.
- Turn it off with `ECOREVIVE_VISION_ENABLED=false`. Change the rule with `ECOREVIVE_VERDICT_RULE` (`gemini`, `yolo`, `gated`).
