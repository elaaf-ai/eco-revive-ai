# Requirements checklist

Maps the *Mid year evaluation Action plan* (`docs/inputs/`) and the project brief to what was built and how it was checked. Updated 2026-11-21.

**Legend:**
- ✅ Done and verified
- 🟡 Done, but one check is still open
- 🔴 Not met or not started

**Scope change (team decision):** the product is now **plastic-only**. The model still predicts five classes, but only Plastic is shown (`shared/product.json`). The 85% target is now **photo-level "does this photo contain plastic"**, judged with balanced accuracy.

## Action plan phases

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 0.1 | GitHub repo `eco-revive-ai`, 4 collaborators | 🟡 | Private repo `elaaf-ai/eco-revive-ai`, all work pushed. Collaborators still need to be added by Elaaf |
| 0.2 | Shared storage for data and models | ✅ | Google Drive plus a private Kaggle dataset |
| 1 | TACO + TrashNet dataset, YOLO format | ✅ | `taco-5class-v1` and `v2`: 2,328 train, 172 val and 210 test photos, 0 validation errors (`docs/DATASET.md`) |
| 2 | Train YOLO11 on a GPU, `best.pt` | ✅ | v2 YOLO11s, 60 epochs on a Kaggle T4. Training log and results in `ml/artifacts/0.2.0-preview-small/` |
| 2.9 | Check mAP | ✅ | Validation and a single locked test run (`docs/EVALUATION.md`) |
| 3 | Export TFLite | ✅ | ONNX and TFLite match `best.pt` exactly (100% of detections matched, confidence difference 0.0) |
| 4 | Flutter app: Home → Camera → Result | 🟡 | APK built with the v2 model. Tests and analysis pass. A **real-phone camera test** is still open |
| 4.4 | Real TFLite detection in the app | 🟡 | Runs on device in a background isolate. Emulator test in `mobile/integration_test/`. A real-phone test is still open |
| 5 | Gemini upcycling guides | ✅ | Live on the website. Hazardous items always get curated disposal steps |
| 6 | Live demo: camera in, guide out | ✅ | https://ecorevive-ai.vercel.app (HTTPS, works on phones) |
| 7 | Methodology, architecture diagram | ✅ | `docs/ARCHITECTURE.md`, `DATASET.md`, `MODEL_CARD.md`, `EVALUATION.md` |
| 8 | Team test: 4 people × 10 objects, fix and retest | 🔴 | Sheet ready at `docs/team_test_sheet.csv`. Only the team can run the tests |
| 9 | Demo rehearsal, timing, Gantt | 🔴 | Script in `docs/DEMO.md`. The rehearsal is the team's |

## Product and engineering

| Requirement | Status | Evidence |
|---|---|---|
| Website: Home, Scan, Results; webcam, phone camera, upload | ✅ | 45 browser checks at 390, 768 and 1440 px |
| Item codes (001–014): recycling and upcycling methods by code | ✅ | `shared/plastic_catalog.json`, live search bar |
| Error states: permission denied, no camera, no detections, uncertain, busy, slow, offline | ✅ | Unit and browser tests |
| Safety: hazardous items get disposal steps (including typed names), glass and metal precautions, "a photo can't confirm safety" | ✅ | `test_qa_regressions.py` (B-01, B-02) |
| Typed, versioned API, health and readiness checks, overload handling, idempotent retries, rate limits | ✅ | 88 backend tests |
| QA bug report, 27 items | 🟡 | All fixed with regression tests (`docs/QA_FIXES.md`). B-16 and B-17 still need a phone test |
| Free HTTPS deployment | ✅ | Vercel Hobby plan, smoke-tested after each deploy |
| CI: lint, tests, builds, gated release, rollback | 🟡 | Workflows are in the repo. The latest CI result has to be confirmed on GitHub's Actions page |
| **85% photo-level accuracy** | 🔴 | Locked test: 68.1% plain accuracy (the "always plastic" baseline is 70.5%) and 56.8% balanced accuracy. Needs real, team-taken photos |
