"""Generate ml/notebooks/ecorevive_train.ipynb, the reproducible successor to fyp.ipynb."""

from __future__ import annotations

import json
from pathlib import Path

CELLS = [
    (
        "markdown",
        """# EcoRevive detector training

Successor to `fyp.ipynb`. It keeps the notebook's Nano and Small settings and replaces the
recursive ZIP search with one explicit, checksummed dataset path.

1. Upload `ecorevive-colab-bundle.zip` to the Drive folder named in `DRIVE_ROOT`.
2. Select **Runtime > Change runtime type > GPU**.
3. Paste the bundle checksum into `BUNDLE_SHA256`, then run the cells in order.

Interrupted runs resume from `last.pt` when you run the training cell again.""",
    ),
    (
        "code",
        """# Explicit inputs. Nothing below searches Drive for a dataset.
DRIVE_ROOT = '/content/drive/MyDrive/FYP/ecorevive'
BUNDLE_ZIP = f'{DRIVE_ROOT}/ecorevive-colab-bundle.zip'
BUNDLE_SHA256 = 'PASTE_SHA256_FROM_package_for_colab'
MODEL_VERSION = '0.1.0-preview'
RUNS_DIR = f'{DRIVE_ROOT}/runs'
REPORTS_DIR = f'{DRIVE_ROOT}/reports'
ARTIFACTS_DIR = f'{DRIVE_ROOT}/artifacts'""",
    ),
    (
        "code",
        """from google.colab import drive
drive.mount('/content/drive')
%pip install -q ultralytics==8.4.212 imagehash onnx onnxruntime""",
    ),
    (
        "code",
        """import hashlib, os, pathlib, shutil, sys, zipfile
import yaml

bundle = pathlib.Path(BUNDLE_ZIP)
if not bundle.is_file():
    raise FileNotFoundError(f'Dataset bundle not found: {bundle}')

digest = hashlib.sha256()
with bundle.open('rb') as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
        digest.update(chunk)
if digest.hexdigest() != BUNDLE_SHA256:
    raise ValueError(f'Checksum mismatch: {digest.hexdigest()}')

WORK = pathlib.Path('/content/ecorevive')
shutil.rmtree(WORK, ignore_errors=True)
with zipfile.ZipFile(bundle) as archive:
    archive.extractall(WORK)

DATA_YAML = WORK / 'dataset' / 'data.yaml'
config = yaml.safe_load(DATA_YAML.read_text())
config['path'] = str(WORK / 'dataset')
DATA_YAML.write_text(yaml.safe_dump(config, sort_keys=False))

os.chdir(WORK / 'code')
sys.path.insert(0, str(WORK / 'code' / 'ml'))
from ecorevive_ml.labels import canonical_names
names = [config['names'][i] for i in sorted(config['names'])]
assert names == canonical_names(), f'Unexpected classes: {names}'
for folder in (RUNS_DIR, REPORTS_DIR, ARTIFACTS_DIR):
    os.makedirs(folder, exist_ok=True)
print('Dataset verified:', names)""",
    ),
    (
        "code",
        """# Train both notebook baselines, resuming any interrupted run from Drive.
import subprocess

def train(baseline):
    name = f'ecorevive_{baseline}'
    last = pathlib.Path(RUNS_DIR) / name / 'weights' / 'last.pt'
    if (last.parents[1] / 'complete.json').exists():
        print(f'{name}: already finished')
        return
    command = [sys.executable, 'ml/scripts/train.py', '--data', str(DATA_YAML),
               '--baseline', baseline, '--project', RUNS_DIR, '--name', name]
    if last.exists():
        command += ['--resume', str(last)]
    subprocess.run(command, check=True)

train('nano')
train('small')""",
    ),
    (
        "code",
        """# Choose the candidate on validation data only.
import json

scores = {}
for baseline in ('nano', 'small'):
    weights = pathlib.Path(RUNS_DIR) / f'ecorevive_{baseline}' / 'weights' / 'best.pt'
    if not weights.exists():
        print(f'{baseline}: no best.pt, skipped')
        continue
    out = pathlib.Path(REPORTS_DIR) / baseline
    subprocess.run([sys.executable, 'ml/scripts/evaluate.py', '--weights', str(weights),
                    '--data', str(DATA_YAML), '--split', 'val', '--out', str(out)], check=True)
    report = json.loads((out / 'eval_best_pt_val.json').read_text())
    scores[baseline] = (report['map50'], str(weights))
    print(baseline, 'val mAP@0.50 =', report['map50'])

CANDIDATE = max(scores, key=lambda k: scores[k][0])
CANDIDATE_WEIGHTS = scores[CANDIDATE][1]
print('Candidate:', CANDIDATE, CANDIDATE_WEIGHTS)""",
    ),
    (
        "code",
        """# Export ONNX and TFLite, then compare each with the checkpoint on validation images.
subprocess.run([sys.executable, 'ml/scripts/export_model.py', '--weights', CANDIDATE_WEIGHTS,
                '--val-images', str(WORK / 'dataset' / 'images' / 'val'),
                '--version', MODEL_VERSION, '--out', ARTIFACTS_DIR], check=False)
print((pathlib.Path(ARTIFACTS_DIR) / MODEL_VERSION / 'manifest.json').read_text())""",
    ),
    (
        "markdown",
        """## Locked test evaluation

Run this once, after the candidate is final. Do not change the model or thresholds based on
these numbers. Every run is recorded in `test_ledger.jsonl`.""",
    ),
    (
        "code",
        """artifact_dir = pathlib.Path(ARTIFACTS_DIR) / MODEL_VERSION
for file in ('best.pt', 'model.onnx', 'model.tflite'):
    path = artifact_dir / file
    if path.exists():
        subprocess.run([sys.executable, 'ml/scripts/evaluate.py', '--weights', str(path),
                        '--data', str(DATA_YAML), '--split', 'test', '--confirm-locked-test',
                        '--out', REPORTS_DIR], check=True)""",
    ),
]


def main() -> None:
    cells = []
    for index, (kind, source) in enumerate(CELLS):
        cell = {
            "cell_type": kind,
            "id": f"cell-{index}",
            "metadata": {},
            "source": source.splitlines(keepends=True),
        }
        if kind == "code":
            cell |= {"execution_count": None, "outputs": []}
        cells.append(cell)

    notebook = {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    target = Path(__file__).resolve().parents[1] / "notebooks" / "ecorevive_train.ipynb"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
