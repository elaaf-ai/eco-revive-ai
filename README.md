# EcoRevive

Scan a piece of waste, see what it is, and get a practical upcycling idea or safe disposal steps.

- **Website** (primary): camera or photo upload → bounding boxes → pick an item → guide. React + FastAPI, one container.
- **Android app**: Home → Camera → Results with the TFLite model running on the phone.
- **Detector**: YOLO11, five classes: Plastic, Glass, Metal, Organic, Hazardous (`shared/classes.json`).
- **Guides**: Gemini on the server, with curated guides for hazardous items and as a fallback (`shared/curated_guides.json`).

> **Model status:** `0.1.0-preview` has been trained in Colab and exported, but it has **not** passed the locked test evaluation. The 0.85 mAP@0.50 target has not been shown. See [docs/EVALUATION.md](docs/EVALUATION.md).

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
