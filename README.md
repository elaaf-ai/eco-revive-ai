# EcoRevive

Scan a piece of plastic waste, or type an item code such as 001 (water bottle), to get its recycling steps and an upcycling project. The 14 coded items are listed in shared/plastic_catalog.json and on the site.

**Live:** https://ecorevive-ai.vercel.app (Vercel free plan, Neon Postgres, plastic-only mode). On the locked test photos the system answers "does this photo contain plastic?" correctly **81.0%** of the time (balanced accuracy 78.0%); see [docs/EVALUATION.md](docs/EVALUATION.md).

- **Website** (primary): camera or photo upload → numbered, named boxes ("Plastic 1 · plastic cup · #1 PET") → pick an item → guide → "Was it right?".
- **Android app**: Home → Camera → Results with the TFLite model on the phone, then the same AI check from the server when online.
- **Detector**: YOLO11, five classes: Plastic, Glass, Metal, Organic, Hazardous (`shared/classes.json`).
- **AI check**: Gemini vision confirms plastic per box, names the item and its likely resin code, and removes wrong boxes.
- **Guides**: Gemini on the server, with curated guides for hazardous items and as a fallback (`shared/curated_guides.json`).
- **Adaptive learning**: user feedback and consented photos become training data; a retrained model goes live only if it scores better ([docs/ADAPTIVE_LEARNING.md](docs/ADAPTIVE_LEARNING.md)).

## Project objectives

| Objective | How it is met | Evidence |
|---|---|---|
| AI-based waste detection | YOLO11s detector (web: ONNX on the server; phone: TFLite on device) plus a Gemini vision check per box | Locked test 81.0% photo accuracy, 78.0% balanced (detector alone 68.1%): `ml/reports/hybrid/test_ledger.jsonl` |
| AI-generated upcycling guides | Gemini writes a guide for the identified item, with safety filters, hazard rules, curated fallbacks and "Another idea" | `backend/app/guides.py`, `backend/tests/test_guides.py` |
| Low cost and low latency | Free tiers only (Vercel, Neon, Kaggle, Gemini). About 1 s per scan without the AI check, about 3 s with it, about 0.2 s on the phone offline; live preview at about 1 frame per second | Load test in docs/EVALUATION.md; smoke test in `deploy/deploy_vercel.py` |
| Plastic core identification | Every AI-checked box gets its likely resin code (#1 PET … #7 Other), marked "likely" unless the number is visible or the item is almost always that plastic, and is linked to the item code (001–014) | `backend/app/vision.py`, `test_plastic_type_from_gemini_or_the_catalogue` |
| Mobile app deployment | Flutter Android app with on-device detection, the server AI check, names, plastic types and feedback; the website also works on phones | `mobile/`, `flutter test` (19 tests); APK in `mobile/build/app/outputs/flutter-apk/` |
| Adaptive learning system | Feedback ("Was it right?") and consented photos → `export_feedback.py` builds the next training set → Kaggle retrain → `promote_model.py` promotes only a better model | [docs/ADAPTIVE_LEARNING.md](docs/ADAPTIVE_LEARNING.md), `ml/tests/test_adaptive_learning.py`, `ml/reports/promotion_ledger.jsonl` |

## Repository

| Path | What it holds |
|---|---|
| `ml/` | Label mapping, dataset build and validation, training, evaluation, export, Colab notebook |
| `backend/` | FastAPI API: ONNX inference, guides, limits, idempotency, health |
| `web/` | React + TypeScript + Vite client, unit tests, Playwright checks |
| `mobile/` | Flutter Android app with on-device TFLite |
| `shared/` | Canonical classes and curated guides used by every component |
| `models/registry/` | Model release records: checksums and evaluation status |
| `docs/` | Architecture, requirements checklist, dataset, model card, evaluation, runbook, test sheet, demo |

## Quick start (Windows)

```powershell
cd eco-revive-ai
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Open http://localhost:8000. The script sets up the backend environment on first run, builds the website if needed, and installs the trained model from `ml\artifacts\0.1.0-preview\` if present (checksum verified). Without the model, it uses the fixture model and says so. To use Gemini, put `GEMINI_API_KEY=...` in `backend\.env`; that file is gitignored. Press Ctrl+C to stop.

## Run the parts separately (for development; use `bin/` instead of `Scripts\` on macOS/Linux)

```powershell
# 1. Backend (Python 3.14)
cd backend
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install --no-deps -r requirements.txt
.venv\Scripts\python -m pip install -r requirements-dev.txt
# Install the model (checksum verified) from the files you downloaded from Drive:
.venv\Scripts\python scripts\fetch_model.py --version 0.1.0-preview --source-dir ..\ml\artifacts\0.1.0-preview --out models\current
$env:ECOREVIVE_MODEL_DIR="models/current"; $env:GEMINI_API_KEY="<optional>"
.venv\Scripts\python -m uvicorn app.main:create_app --factory --port 8000

# 2. Web (Node 24), in a second terminal
cd web
npm ci
npm run dev        # http://localhost:5173 (proxies /v1 to :8000)
```

No model yet? Use the fixture model for UI work only. It returns fixed boxes and says so in the UI:
`.venv\Scripts\python scripts\fixture_model.py --out models\fixture` and set `ECOREVIVE_MODEL_DIR=models/fixture`.

Production-style, one container: `docker compose up --build` → http://localhost:8000. See [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Checks

```powershell
cd ml;      .venv\Scripts\python -m pytest tests -q
cd backend; .venv\Scripts\python -m pytest -q; .venv\Scripts\python -m mypy app; .venv\Scripts\ruff check --config ..\ruff.toml .
cd web;     npm run lint; npm run typecheck; npm test; npm run build; npx playwright test
cd mobile;  flutter analyze; flutter test
```

## Training and export

Training runs in Google Colab, because Windows Application Control blocks PyTorch on the team laptop. See [ml/README.md](ml/README.md).

## Android

See [mobile/README.md](mobile/README.md).

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Requirements checklist](docs/REQUIREMENTS.md) · [Dataset](docs/DATASET.md) · [Model card](docs/MODEL_CARD.md) · [Evaluation](docs/EVALUATION.md) · [Runbook](docs/RUNBOOK.md) · [Team test sheet](docs/TEAM_TEST_PLAN.md) · [Demo and timeline](docs/DEMO.md)
