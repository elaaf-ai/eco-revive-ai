# Detection pipeline

All commands run from the repository root. Seed 42 everywhere.

| Step | Command | Output |
|---|---|---|
| Download TACO (pinned commit) | `python ml/scripts/download_taco.py` | `ml/data/raw/taco/` |
| Build 5-class dataset | `python ml/scripts/prepare_taco.py --seed 42` | `ml/data/processed/taco-5class-v1/`, `ml/manifests/*` |
| Validate | `python ml/scripts/validate_dataset.py --data ml/data/processed/taco-5class-v1/data.yaml` | exit 0 when valid |
| Package for Colab | `python ml/scripts/package_for_colab.py` | `ml/artifacts/ecorevive-colab-bundle.zip` + SHA-256 |
| Train (Colab) | `ml/notebooks/ecorevive_train.ipynb` | Drive `FYP/ecorevive/runs/` |
| Train (GPU machine) | `python ml/scripts/train.py --data <data.yaml> --baseline nano` | `ml/runs/ecorevive_nano/` |
| Resume | `python ml/scripts/train.py --data <data.yaml> --resume ml/runs/ecorevive_nano/weights/last.pt` | |
| Check a checkpoint | `python ml/scripts/inspect_checkpoint.py --weights best.pt --samples <folder>` | exit 2 on class mismatch |
| Select on validation | `python ml/scripts/evaluate.py --weights best.pt --data <data.yaml> --split val` | `ml/reports/eval_*_val.json` |
| Export + parity | `python ml/scripts/export_model.py --weights best.pt --val-images <val images> --version 0.1.0-preview` | `ml/artifacts/<version>/` |
| Locked test (once) | `python ml/scripts/evaluate.py ... --split test --confirm-locked-test` | report + `test_ledger.jsonl` |

Baselines come from `fyp.ipynb`: YOLO11n 25 epochs and YOLO11s 60 epochs with patience 20, both at 640 px with batch 16 (`ml/configs/baselines.yaml`).

## Environment

- Colab: the notebook installs `ultralytics==8.4.212` (the version logged in `fyp.ipynb`).
- Local: Python 3.14, `ml/requirements.txt`, exact set in `ml/requirements.lock.txt`. On the team laptop, Windows Application Control blocks the PyTorch DLLs, so local training and `.pt` inference are not possible there. Dataset preparation, validation and tests run locally.

## Why the notebook changed

`fyp.ipynb` searched all of Drive for any ZIP whose name contained "taco", "trashnet" or "yolov11", then used the first `data.yaml` inside it. Its saved outputs show that dataset had **4 classes** (filenames such as `paper134` suggest Paper was one), and that both runs stopped early (Nano at epoch 12/25, Small at epoch 10/60). The new notebook takes one explicit bundle path, verifies its checksum, and refuses any dataset whose classes differ from `shared/classes.json`.
