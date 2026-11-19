"""Generate ml/notebooks/ecorevive_train.ipynb, the reproducible successor to fyp.ipynb.

The notebook uses Google Drive when it can be mounted. If mounting fails, it works from a bundle
uploaded straight into Colab and offers the results as a ZIP download at the end.
"""

from __future__ import annotations

import json
from pathlib import Path

CELLS = [
    (
        "markdown",
        """# EcoRevive detector training

Keeps the Nano and Small settings from `fyp.ipynb`, with one explicit, checksummed dataset bundle.

**Option A, with Google Drive:** upload the bundle ZIP to `My Drive/FYP/ecorevive/`.
**Option B, without Drive:** open the Files sidebar (folder icon), click Upload, and upload the
bundle ZIP into `/content`. Keep the tab open while training runs.

Then: **Runtime → Change runtime type → T4 GPU**, paste the bundle checksum below, and run the cells
in order. Stop before the locked test cell.""",
    ),
    (
        "code",
        """# Explicit inputs. Nothing below searches for a dataset.
DATASET_VERSION = 'taco-5class-v2'
MODEL_VERSION = '0.2.0-preview'
BUNDLE_NAME = 'ecorevive-colab-bundle-v2.zip'
BUNDLE_SHA256 = 'PASTE_SHA256_HERE'
DRIVE_ROOT = '/content/drive/MyDrive/FYP/ecorevive'""",
    ),
    (
        "code",
        """%pip install -q ultralytics==8.4.212 onnx onnxruntime
import ultralytics; print('ultralytics', ultralytics.__version__)""",
    ),
    (
        "code",
        """# Use Drive if it mounts; otherwise work locally in /content.
import os
USE_DRIVE = False
try:
    from google.colab import drive
    drive.mount('/content/drive')
    USE_DRIVE = os.path.isdir(DRIVE_ROOT)
except Exception as error:
    print('Drive not available, using local mode:', error)

BASE = DRIVE_ROOT if USE_DRIVE else '/content/ecorevive-out'
BUNDLE_ZIP = f'{DRIVE_ROOT}/{BUNDLE_NAME}' if USE_DRIVE and os.path.exists(f'{DRIVE_ROOT}/{BUNDLE_NAME}') \\
    else f'/content/{BUNDLE_NAME}'
RUNS_DIR = f'{BASE}/runs-{DATASET_VERSION}'
REPORTS_DIR = f'{BASE}/reports-{DATASET_VERSION}'
ARTIFACTS_DIR = f'{BASE}/artifacts'
print('Drive' if USE_DRIVE else 'Local (results are lost if the runtime disconnects)')
print('Bundle:', BUNDLE_ZIP)""",
    ),
    (
        "code",
        """import hashlib, pathlib, shutil, sys, zipfile
import yaml

bundle = pathlib.Path(BUNDLE_ZIP)
if not bundle.is_file():
    raise FileNotFoundError(f'Upload {BUNDLE_NAME} first: {bundle}')
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
        """# Train both notebook baselines; an interrupted run resumes from last.pt.
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
        """# Choose the candidate on validation data only (same validation photos as v1).
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
    print(baseline, 'val mAP@0.50 =', report['map50'],
          {k: (v or {}).get('ap50') for k, v in report['per_class'].items()})

CANDIDATE = max(scores, key=lambda k: scores[k][0])
CANDIDATE_WEIGHTS = scores[CANDIDATE][1]
print('Candidate:', CANDIDATE, CANDIDATE_WEIGHTS)""",
    ),
    (
        "code",
        """# Export ONNX and TFLite and compare each with the checkpoint on identical 640x640 inputs.
subprocess.run([sys.executable, 'ml/scripts/export_model.py', '--weights', CANDIDATE_WEIGHTS,
                '--val-images', str(WORK / 'dataset' / 'images' / 'val'),
                '--version', MODEL_VERSION, '--out', ARTIFACTS_DIR], check=False)
print((pathlib.Path(ARTIFACTS_DIR) / MODEL_VERSION / 'manifest.json').read_text())""",
    ),
    (
        "code",
        """# Download the model files (needed in local mode; handy with Drive too).
archive = shutil.make_archive(f'/content/ecorevive-{MODEL_VERSION}', 'zip',
                              pathlib.Path(ARTIFACTS_DIR) / MODEL_VERSION)
from google.colab import files
files.download(archive)""",
    ),
    (
        "markdown",
        """## Locked test evaluation (do not run yet)

Run once, only after the team has chosen the final model. Every run is written to `test_ledger.jsonl`.""",
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
        cell = {"cell_type": kind, "id": f"cell-{index}", "metadata": {}, "source": source.splitlines(keepends=True)}
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
