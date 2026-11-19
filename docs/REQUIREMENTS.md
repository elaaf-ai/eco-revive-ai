# Requirements checklist

Maps the *Mid year evaluation Action plan* (`docs/inputs/`) and the project brief to what was built and how it was checked. Status as of 2026-11-19.

**Legend:**
- ✅ Done and verified
- 🟡 Built, but verification is blocked or partial
- ⛔ Blocked on an external input
- ⬜ Not started

## Action plan phases

| # | Requirement | Status | Implementation | Verification |
|---|---|---|---|---|
| 0.1 | GitHub repo `eco-revive-ai`, 4 collaborators | ⛔ | Local git repo with 5 commits | Pushing needs GitHub sign-in on this PC; collaborators need GitHub usernames |
| 0.2 | Shared Drive for datasets and models | ✅ | `My Drive/FYP/ecorevive/` holds the bundle, runs and artifacts | Colab run completed |
| 1 | TACO + TrashNet merged into 5 classes, YOLO format | 🟡 | TACO mapped with `ml/configs/taco_mapping_v1.yaml`. TrashNet excluded because it has no boxes | `validate_dataset.py`: 0 errors. Organic and Hazardous are too sparse |
| 2 | Train YOLO11 in Colab, `best.pt` | ✅ | `ml/notebooks/ecorevive_train.ipynb`, using the Nano and Small baselines from `fyp.ipynb` | Export manifest with checksums |
| 2.9 | Check mAP | ⛔ | `ml/scripts/evaluate.py`, with a locked test ledger | Validation and test numbers not yet reported back from Colab |
| 3 | Export TFLite | 🟡 | `export_model.py`: ONNX + TFLite + parity check | Exported. Parity re-check pending (first check was flawed, now fixed) |
| 4 | Flutter app: Home → Camera → Result | ✅ | `mobile/` | `flutter analyze` clean, 10 tests pass, APK runs on the API 37 emulator |
| 4.4 | Real TFLite detection in the app | 🟡 | `lib/detection/` runs decode, rotation, letterbox, TFLite and NMS in an isolate | Unit-tested. On-device run needs `model.tflite` copied into `assets/model/` |
| 5 | Gemini `get_upcycling_guide(category)` | 🟡 | `backend/app/guides.py` uses the `google-genai` SDK, `client.aio.interactions.create`, model `gemini-3.5-flash-lite` (configurable) | Mocked tests pass. A live call needs `GEMINI_API_KEY` |
| 6 | Live demo: camera in, guide out | 🟡 | Web: live preview + capture → boxes → guide. Android: capture → boxes → guide | Full flow passes in Playwright with the fixture model. A real-model run needs the ONNX file |
| 7 | Methodology, architecture diagram | ✅ | `docs/ARCHITECTURE.md`, `DATASET.md`, `MODEL_CARD.md` | |
| 8 | Team test: 4 people × 10 objects, fix and retest | ⬜ | `docs/TEAM_TEST_PLAN.md`, `docs/team_test_sheet.csv` | Sheet is empty on purpose: record only real tests |
| 9 | Demo rehearsal, timing, Gantt | 🟡 | `docs/DEMO.md` | Rehearsal not yet held |

## Product and engineering brief

| Requirement | Status | Evidence |
|---|---|---|
| Five canonical classes everywhere | ✅ | `shared/classes.json`, checked by ML tests, the backend at model load, ONNX metadata, and a Flutter test |
| Web: Home, Scan, Results; webcam, phone camera and upload | ✅ | Playwright at 390, 768 and 1440 px with Chrome's fake camera |
| Permission denied, no camera, insecure context, no detections, low confidence, ambiguous, busy, slow, model offline | ✅ | Unit and e2e tests; screenshots in `docs/screenshots/` |
| Sustainable frame sampling, stale responses dropped, camera stopped on leave | ✅ | `Scanner.tsx` live loop; e2e checks camera tracks stop on leaving |
| Hazardous → curated guidance; glass and metal precautions; "photo can't confirm safety" | ✅ | `test_guides.py`, `ResultsPanel.test.tsx`, Flutter tests |
| Original visual design, keyboard, focus, live announcements, reduced motion | ✅ | Screenshots reviewed by eye; keyboard e2e test; `prefers-reduced-motion` rule |
| Typed, versioned API with OpenAPI; liveness and readiness | ✅ | `/docs`, `/healthz`, `/readyz`; contract tests |
| Model warmed once, inference off the event loop, bounded queue, timeouts, 503 when overloaded | ✅ | `test_api.py`; load test: 375 of 400 rejected cleanly at 16 concurrent clients |
| Idempotency: scoped keys, fingerprint, in-flight coalescing, TTL, reuse rejected | ✅ | `test_api.py` (replay, concurrent duplicates, key reuse, failures not stored) |
| Upload limits, decode validation, pixel cap, metadata stripped, images not stored | ✅ | `test_imaging_detector.py` |
| Secrets server-side, `.env.example`, structured logs, request IDs, metrics | ✅ | `config.py`, `observability.py`, `/v1/metrics` |
| Model checksums, versioned registry, checksum-verified install | ✅ | `models/registry/`, `fetch_model.py` refuses a mismatch (tested) |
| CI for lint, tests and builds; manual GPU training; gated release; rollback | 🟡 | Workflows written. Not run until the repo is on GitHub |
| Docker image | 🟡 | Dockerfile and compose written. Docker is not installed here, so the image hasn't been built locally; CI builds it |
| ≥ 0.85 mAP@0.50 on the locked test split | ⛔ | Not evaluated. Likely to miss until Organic and Hazardous data is collected |
| HTTPS deployment, phone camera test over HTTPS | ⛔ | Needs a hosting choice and account |
| Release APK | 🟡 | `app-release.apk` (68.7 MB) built, debug-signed, without the model |
