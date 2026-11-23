"""Adaptive learning, step 3: put a retrained model live only if it is better.

Evaluates the current model and the candidate on the same validation photos with
evaluate_onnx.py, then compares:

- photo-level balanced accuracy for "does this photo contain plastic?" (app threshold 0.25);
- Plastic AP@0.50.

The candidate is promoted only if its balanced accuracy is higher by at least --min-gain and its
Plastic AP@0.50 is not lower by more than --ap-tolerance. On promotion the current model is kept
in backend/models/previous for rollback. Every decision is appended to
ml/reports/promotion_ledger.jsonl. The locked test split is never used here.

  backend/.venv/Scripts/python ml/scripts/promote_model.py --candidate path/to/artifacts/0.3.0-preview
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "backend" / "models" / "current"
PREVIOUS = ROOT / "backend" / "models" / "previous"
REPORTS = ROOT / "ml" / "reports" / "promotion"
LEDGER = ROOT / "ml" / "reports" / "promotion_ledger.jsonl"


def evaluate(model_dir: Path, data: Path) -> dict:
    """Run evaluate_onnx.py on the validation split and return the key numbers."""
    out = REPORTS / model_dir.name
    subprocess.run(
        [sys.executable, str(ROOT / "ml/scripts/evaluate_onnx.py"), "--model-dir", str(model_dir),
         "--data", str(data), "--split", "val", "--out", str(out)],
        check=True, stdout=subprocess.DEVNULL,
    )
    report = json.loads(next(out.glob("eval_onnx_*_val.json")).read_text(encoding="utf-8"))
    return summarise(report)


def summarise(report: dict) -> dict:
    per_class = report["per_class"]
    plastic = per_class["Plastic"] if isinstance(per_class, dict) else per_class[0]
    photo = report["photo_level"]["at_app_threshold_0.25"]
    return {
        "model_version": report["model_version"],
        "plastic_ap50": plastic["ap50"],
        "balanced_accuracy": photo["balanced_accuracy"],
        "accuracy": photo["accuracy"],
    }


def decide(current: dict, candidate: dict, min_gain: float, ap_tolerance: float) -> tuple[bool, str]:
    gain = candidate["balanced_accuracy"] - current["balanced_accuracy"]
    ap_drop = current["plastic_ap50"] - candidate["plastic_ap50"]
    if gain < min_gain:
        return False, f"balanced accuracy gain {gain:+.3f} is below the required {min_gain:+.3f}"
    if ap_drop > ap_tolerance:
        return False, f"Plastic AP50 fell by {ap_drop:.3f} (allowed {ap_tolerance:.3f})"
    return True, f"balanced accuracy {gain:+.3f}, Plastic AP50 {-ap_drop:+.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", type=Path, required=True, help="Folder with model.onnx and manifest.json")
    parser.add_argument("--data", type=Path, default=ROOT / "ml/data/processed/taco-5class-v1/data.yaml")
    parser.add_argument("--min-gain", type=float, default=0.01)
    parser.add_argument("--ap-tolerance", type=float, default=0.02)
    parser.add_argument("--dry-run", action="store_true", help="Compare and record, but do not replace the model")
    args = parser.parse_args()

    current = evaluate(CURRENT, args.data)
    candidate = evaluate(args.candidate, args.data)
    promote, reason = decide(current, candidate, args.min_gain, args.ap_tolerance)
    entry = {"decided_at": datetime.now(UTC).isoformat(), "current": current, "candidate": candidate,
             "promoted": promote and not args.dry_run, "dry_run": args.dry_run, "reason": reason}
    print(json.dumps(entry, indent=2))
    if promote and not args.dry_run:
        shutil.rmtree(PREVIOUS, ignore_errors=True)
        shutil.copytree(CURRENT, PREVIOUS)
        for name in ("model.onnx", "manifest.json"):
            shutil.copy2(args.candidate / name, CURRENT / name)
        print("Promoted. Redeploy with deploy/deploy_vercel.py; roll back from backend/models/previous.")
    else:
        print("Not promoted." if not promote else "Dry run: not promoted.")
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
