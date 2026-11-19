"""Evaluate a model on one split and write a JSON report.

Use val for model selection. The test split needs --confirm-locked-test, and every test
access is appended to a ledger so repeated use of the holdout stays visible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.labels import canonical_names

TARGET_MAP50 = 0.85


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True, help="Explicit path to data.yaml")
    parser.add_argument("--split", choices=["val", "test"], default="val")
    parser.add_argument("--confirm-locked-test", action="store_true")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default=None)
    parser.add_argument("--out", type=Path, default=Path("ml/reports"))
    args = parser.parse_args()

    if args.split == "test" and not args.confirm_locked_test:
        parser.error("The test split is locked. Pass --confirm-locked-test for the final evaluation only.")

    names = canonical_names()
    model = YOLO(str(args.weights))
    metrics = model.val(
        data=str(args.data), split=args.split, imgsz=args.imgsz, device=args.device, plots=True, verbose=False
    )

    per_class = {name: None for name in names}
    for index, class_id in enumerate(metrics.box.ap_class_index):
        per_class[names[int(class_id)]] = {
            "ap50": round(float(metrics.box.ap50[index]), 4),
            "ap50_95": round(float(metrics.box.ap[index]), 4),
            "precision": round(float(metrics.box.p[index]), 4),
            "recall": round(float(metrics.box.r[index]), 4),
            "instances": int(metrics.nt_per_class[int(class_id)]),
        }

    map50 = round(float(metrics.box.map50), 4)
    report = {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "weights": args.weights.name,
        "sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "split": args.split,
        "map50": map50,
        "map50_95": round(float(metrics.box.map), 4),
        "precision": round(float(metrics.box.mp), 4),
        "recall": round(float(metrics.box.mr), 4),
        "per_class": per_class,
        "classes_without_instances": [name for name, value in per_class.items() if value is None],
        "speed_ms_per_image": {k: round(v, 2) for k, v in metrics.speed.items()},
        "confusion_matrix": metrics.confusion_matrix.matrix.astype(int).tolist(),
        "target_map50": TARGET_MAP50,
        "meets_target": args.split == "test" and map50 >= TARGET_MAP50,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"eval_{args.weights.stem}_{args.weights.suffix.lstrip('.')}_{args.split}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.split == "test":
        with (args.out / "test_ledger.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write(
                json.dumps({k: report[k] for k in ("evaluated_at", "weights", "sha256", "map50")}) + "\n"
            )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
