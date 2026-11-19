"""Kaggle GPU job: train the notebook baselines on the EcoRevive v2 bundle and export them.

Runs unattended as a Kaggle script kernel. Everything the team needs ends up in
/kaggle/working/out: weights, results.csv, validation reports, ONNX/TFLite exports with parity
results, and a status.json describing what finished. Errors are written to error.txt.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path

BUNDLE_SHA256 = "32d2663b5b649a4ff379a3c07ead2826acd4bdcd1952e3ca336be3f52ce5c4fb"
MODEL_VERSION = "0.2.0-preview"
OUT = Path("/kaggle/working/out")
WORK = Path("/tmp/ecorevive")
RUNS = Path("/tmp/runs")
status: dict = {"model_version": MODEL_VERSION, "started": time.time(), "steps": {}}


def save_status() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "status.json").write_text(json.dumps(status, indent=2))


def run(step: str, command: list[str], check: bool = True) -> int:
    print(f"\n===== {step}: {' '.join(command)}", flush=True)
    started = time.time()
    code = subprocess.run(command, cwd=WORK / "code").returncode
    status["steps"][step] = {"exit": code, "minutes": round((time.time() - started) / 60, 1)}
    save_status()
    if check and code != 0:
        raise RuntimeError(f"{step} failed with exit code {code}")
    return code


def find_bundle() -> Path:
    for path in Path("/kaggle/input").rglob("*"):
        if path.name == "ecorevive-colab-bundle-v2.zip":
            return path
    for path in Path("/kaggle/input").rglob("data.yaml"):
        if path.parent.name == "dataset":
            return path.parents[1]
    raise FileNotFoundError("Bundle not found under /kaggle/input")


def prepare() -> Path:
    source = find_bundle()
    shutil.rmtree(WORK, ignore_errors=True)
    if source.is_file():
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != BUNDLE_SHA256:
            raise ValueError(f"Bundle checksum mismatch: {digest}")
        with zipfile.ZipFile(source) as archive:
            archive.extractall(WORK)
        status["bundle"] = {"source": str(source), "sha256_verified": True}
    else:
        shutil.copytree(source, WORK)
        status["bundle"] = {"source": str(source), "sha256_verified": False, "note": "Kaggle unpacked the ZIP"}
    data_yaml = WORK / "dataset" / "data.yaml"
    import yaml

    config = yaml.safe_load(data_yaml.read_text())
    config["path"] = str(WORK / "dataset")
    data_yaml.write_text(yaml.safe_dump(config, sort_keys=False))
    counts = {s: len(list((WORK / "dataset" / "images" / s).glob("*.jpg"))) for s in ("train", "val", "test")}
    status["dataset_counts"] = counts
    if counts["val"] != 172 or counts["test"] != 210:
        raise ValueError(f"Unexpected val/test sizes {counts}; holdouts must match v1")
    save_status()
    return data_yaml


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics==8.4.212", "onnx", "onnxruntime",
                    "imagehash"], check=True)
    import torch

    status["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none"
    status["torch"] = torch.__version__
    save_status()
    data_yaml = prepare()

    for baseline in ("small", "nano"):
        name = f"ecorevive_{baseline}"
        run(f"train_{baseline}", [sys.executable, "ml/scripts/train.py", "--data", str(data_yaml),
                                  "--baseline", baseline, "--project", str(RUNS), "--name", name, "--workers", "4"])
        run_dir = RUNS / name
        target = OUT / baseline
        target.mkdir(parents=True, exist_ok=True)
        for file in ("results.csv", "args.yaml", "environment.json", "complete.json"):
            if (run_dir / file).exists():
                shutil.copy2(run_dir / file, target / file)
        weights = run_dir / "weights" / "best.pt"
        run(f"val_{baseline}", [sys.executable, "ml/scripts/evaluate.py", "--weights", str(weights),
                                "--data", str(data_yaml), "--split", "val", "--out", str(target / "reports")],
            check=False)
        run(f"export_{baseline}", [sys.executable, "ml/scripts/export_model.py", "--weights", str(weights),
                                   "--val-images", str(WORK / "dataset" / "images" / "val"),
                                   "--version", f"{MODEL_VERSION}-{baseline}", "--out", str(target / "artifacts")],
            check=False)
        for parity_dir in (target / "artifacts").rglob("parity_inputs"):
            shutil.rmtree(parity_dir, ignore_errors=True)

    status["finished"] = time.time()
    status["ok"] = True
    save_status()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.txt").write_text(traceback.format_exc())
        status["ok"] = False
        save_status()
        raise
    finally:
        os.sync() if hasattr(os, "sync") else None
