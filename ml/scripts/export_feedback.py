"""Adaptive learning, step 1: turn user feedback into training data.

Reads the feedback table (only rows where the user agreed to share the photo), groups the
rows by photo, and writes a YOLO dataset:

- a box the user marked **correct** becomes a Plastic label;
- a box marked **wrong** gets no label, so the model learns that this spot is not plastic;
- a photo whose boxes were all wrong is kept with an empty label file (a "no plastic" example).

With --base, the feedback photos are added to the **train** split of a copy of the base
dataset. Validation and test stay exactly as they are, so the retrained model is compared with
the current one on the same photos (see promote_model.py).

  $env:DATABASE_URL = "<Neon connection string from the Vercel project>"
  backend/.venv/Scripts/python ml/scripts/export_feedback.py \
      --base ml/data/processed/taco-5class-v2 --out ml/data/processed/taco-5class-v3
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.history import HistoryStore  # noqa: E402

PLASTIC = 0


def yolo_line(box: list[float]) -> str:
    x1, y1, x2, y2 = (min(1.0, max(0.0, v)) for v in box)
    return f"{PLASTIC} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {x2 - x1:.6f} {y2 - y1:.6f}"


def group_by_photo(rows: list[dict]) -> dict[str, dict]:
    """One entry per shared photo: its image and the boxes marked correct or wrong."""
    photos: dict[str, dict] = defaultdict(lambda: {"image": None, "correct": [], "wrong": 0, "rows": 0})
    for row in rows:
        if not row.get("image") or row.get("class_name") != "Plastic":
            continue
        entry = photos[row["image_sha256"]]
        entry["image"] = row["image"]
        entry["rows"] += 1
        if row["correct"]:
            entry["correct"].append(row["box"])
        else:
            entry["wrong"] += 1
    return dict(photos)


def write_feedback(photos: dict[str, dict], images_dir: Path, labels_dir: Path) -> dict[str, int]:
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    counts = {"photos": 0, "plastic_boxes": 0, "negative_photos": 0}
    for digest, entry in sorted(photos.items()):
        image = Image.open(io.BytesIO(base64.b64decode(entry["image"]))).convert("RGB")
        name = f"feedback_{digest[:16]}"
        image.save(images_dir / f"{name}.jpg", "JPEG", quality=92)
        lines = [yolo_line(box) for box in entry["correct"]]
        (labels_dir / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        counts["photos"] += 1
        counts["plastic_boxes"] += len(lines)
        counts["negative_photos"] += 0 if lines else 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--base", type=Path, help="Dataset to copy; feedback is added to its train split")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-photos", type=int, default=50, help="Refuse to build with fewer shared photos")
    args = parser.parse_args()
    if not args.database_url:
        sys.exit("Set DATABASE_URL (or pass --database-url).")

    store = HistoryStore(args.database_url, timeout_s=15)
    rows = store.export_feedback(only_with_photos=True)
    store.close()
    photos = group_by_photo(rows)
    print(f"{len(rows)} feedback rows with photos, {len(photos)} distinct photos")
    if len(photos) < args.min_photos:
        sys.exit(f"Only {len(photos)} shared photos; need {args.min_photos} before retraining is worthwhile.")

    if args.out.exists():
        sys.exit(f"{args.out} already exists; choose a new version folder.")
    if args.base:
        shutil.copytree(args.base, args.out)
        yaml_path = args.out / "data.yaml"
        text = yaml_path.read_text(encoding="utf-8")
        yaml_path.write_text(text.replace(str(args.base.resolve()).replace("\\", "/"),
                                          str(args.out.resolve()).replace("\\", "/")), encoding="utf-8")
    counts = write_feedback(photos, args.out / "images" / "train", args.out / "labels" / "train")
    manifest = {
        "built_at": datetime.now(UTC).isoformat(),
        "base": str(args.base) if args.base else None,
        "feedback_rows": len(rows),
        **counts,
        "note": "Feedback photos are added to train only; val and test are unchanged.",
    }
    (args.out / "feedback_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
