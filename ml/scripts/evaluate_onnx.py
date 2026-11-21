"""Evaluate the deployed ONNX model with the backend's own preprocessing, without PyTorch.

Uses the same letterbox, decoding and NMS code as the API, with Ultralytics validation settings
(conf 0.001, NMS IoU 0.7, up to 300 detections). Run with the backend environment:

  backend/.venv/Scripts/python ml/scripts/evaluate_onnx.py --model-dir backend/models/current \
      --data ml/data/processed/taco-5class-v1/data.yaml --split val

The test split is locked: it needs --confirm-locked-test and every run is appended to the ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT / "backend"))

from app.detector import OnnxDetector  # noqa: E402
from ecorevive_ml.labels import canonical_names  # noqa: E402
from ecorevive_ml.metrics import (  # noqa: E402
    ap_per_class,
    best_presence_threshold,
    confusion_matrix,
    match_predictions,
    presence_metrics,
)

TARGET_MAP50 = 0.85


def read_labels(path: Path) -> tuple[np.ndarray, np.ndarray]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    rows = [line.split() for line in text.splitlines() if line.strip()]
    if not rows:
        return np.zeros((0, 4)), np.zeros((0,), dtype=int)
    data = np.array(rows, dtype=float)
    cx, cy, w, h = data[:, 1], data[:, 2], data[:, 3], data[:, 4]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    return boxes, data[:, 0].astype(int)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--split", choices=["val", "test"], default="val")
    parser.add_argument("--confirm-locked-test", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "ml" / "reports")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--presence-class", default="Plastic", help="Class for the photo-level accuracy metric")
    parser.add_argument("--presence-threshold", type=float, default=None,
                        help="Fixed threshold for the test split, chosen on validation beforehand")
    args = parser.parse_args()
    if args.split == "test" and not args.confirm_locked_test:
        parser.error("The test split is locked. Pass --confirm-locked-test for the final evaluation only.")

    names = canonical_names()
    config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    root = args.data.parent
    images = sorted((root / config[args.split]).glob("*.jpg"))
    if not images:
        parser.error(f"No .jpg images found for the {args.split} split in {root / config[args.split]}")
    detector = OnnxDetector(args.model_dir, names, conf_threshold=0.001, iou_threshold=0.7,
                            max_detections=300, threads=args.threads)
    detector.warm_up(2)

    stats_tp, stats_conf, stats_pred, stats_target = [], [], [], []
    matrix = np.zeros((len(names) + 1, len(names) + 1), dtype=int)
    timings: list[float] = []
    presence_id = names.index(args.presence_class)
    has_target: list[bool] = []
    top_scores: list[float] = []
    for image_path in images:
        # Ultralytics layout: .../images/<dir>/x.jpg pairs with .../labels/<dir>/x.txt
        label_path = image_path.parents[2] / "labels" / image_path.parent.name / f"{image_path.stem}.txt"
        gt_boxes, gt_cls = read_labels(label_path)
        with Image.open(image_path) as handle:
            image = handle.convert("RGB")
        started = time.perf_counter()
        detections = detector.predict(image)
        timings.append((time.perf_counter() - started) * 1000)
        boxes = np.array([d.box for d in detections]).reshape(-1, 4)
        conf = np.array([d.confidence for d in detections])
        cls = np.array([d.class_id for d in detections], dtype=int)
        stats_tp.append(match_predictions(boxes, cls, gt_boxes, gt_cls))
        stats_conf.append(conf)
        stats_pred.append(cls)
        stats_target.append(gt_cls)
        matrix += confusion_matrix(boxes, cls, conf, gt_boxes, gt_cls, len(names))
        has_target.append(bool((gt_cls == presence_id).any()))
        top_scores.append(float(conf[cls == presence_id].max()) if (cls == presence_id).any() else 0.0)

    per_class = ap_per_class(
        np.concatenate(stats_tp), np.concatenate(stats_conf), np.concatenate(stats_pred),
        np.concatenate(stats_target), len(names),
    )
    present = [c for c, m in per_class.items() if m.instances > 0]
    map50 = float(np.mean([per_class[c].ap50 for c in present]))

    truth, scores = np.array(has_target), np.array(top_scores)
    if args.split == "val":
        chosen = best_presence_threshold(truth, scores)
        threshold_note = "chosen on this validation split"
    else:
        if args.presence_threshold is None:
            parser.error("--presence-threshold is required on test; take it from the validation report.")
        chosen = args.presence_threshold
        threshold_note = "fixed in advance from validation"
    presence = {
        "class": args.presence_class,
        "question": f"Does the photo contain {args.presence_class.lower()}?",
        "at_app_threshold_0.25": presence_metrics(truth, scores, 0.25),
        "at_chosen_threshold": presence_metrics(truth, scores, chosen) | {"threshold_source": threshold_note},
        "target_accuracy": 0.85,
    }
    report = {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "model_version": detector.version,
        "format": "onnx",
        "sha256": hashlib.sha256((args.model_dir / "model.onnx").read_bytes()).hexdigest(),
        "split": args.split,
        "images": len(images),
        "settings": {"conf": 0.001, "nms_iou": 0.7, "max_det": 300, "imgsz": detector.imgsz,
                     "preprocessing": "backend letterbox (PIL bilinear, pad 114)"},
        "map50": round(map50, 4),
        "map50_95": round(float(np.mean([per_class[c].ap50_95 for c in present])), 4),
        "precision": round(float(np.mean([per_class[c].precision for c in present])), 4),
        "recall": round(float(np.mean([per_class[c].recall for c in present])), 4),
        "per_class": {
            names[c]: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in vars(m).items()}
            for c, m in per_class.items()
        },
        "confusion_matrix": {"rows_predicted_cols_true": names + ["background"], "counts": matrix.tolist()},
        "photo_level": presence,
        "latency_ms": {
            "p50": round(statistics.median(timings), 1),
            "p95": round(sorted(timings)[int(0.95 * (len(timings) - 1))], 1),
            "note": "model forward + pre/post-processing per image on this CPU, one image at a time",
        },
        "target_map50": TARGET_MAP50,
        "meets_target": args.split == "test" and map50 >= TARGET_MAP50,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"eval_onnx_{detector.version}_{args.split}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.split == "test":
        with (args.out / "test_ledger.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps({k: report[k] for k in ("evaluated_at", "model_version", "format", "sha256",
                                                            "map50")}) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
