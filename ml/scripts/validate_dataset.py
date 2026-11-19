"""Validate a YOLO dataset: classes, label format, image pairing and overlap between splits.

Exit codes: 0 valid, 1 errors found. Warnings report sparse classes without failing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from PIL import Image, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.labels import canonical_names

SPLITS = ("train", "val", "test")
MIN_INSTANCES_WARNING = {"train": 50, "val": 10, "test": 10}


def check_label_line(line: str, class_count: int) -> str | None:
    """Return an error message for a malformed YOLO label line, or None when valid."""
    parts = line.split()
    if len(parts) != 5:
        return "expected 5 fields"
    try:
        class_id = int(parts[0])
        x, y, w, h = (float(v) for v in parts[1:])
    except ValueError:
        return "non-numeric field"
    if not 0 <= class_id < class_count:
        return f"class id {class_id} out of range"
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
        return "coordinates outside 0-1"
    if x - w / 2 < -1e-3 or x + w / 2 > 1 + 1e-3 or y - h / 2 < -1e-3 or y + h / 2 > 1 + 1e-3:
        return "box extends outside the image"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Explicit path to data.yaml")
    args = parser.parse_args()

    names = canonical_names()
    config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    declared = [config["names"][i] for i in sorted(config["names"])]
    errors: list[str] = []
    warnings: list[str] = []
    if declared != names:
        errors.append(f"data.yaml classes {declared} differ from canonical {names}")

    root = args.data.parent
    digests: dict[str, set[str]] = defaultdict(set)
    report: dict[str, dict] = {}
    for split in SPLITS:
        images = sorted((root / "images" / split).glob("*.jpg"))
        labels = {p.stem for p in (root / "labels" / split).glob("*.txt")}
        instances: Counter = Counter()
        if not images:
            errors.append(f"{split}: no images")
        for stem in sorted(labels - {p.stem for p in images}):
            errors.append(f"{split}/{stem}: label without image")
        for image in images:
            digests[split].add(hashlib.sha256(image.read_bytes()).hexdigest())
            try:
                with Image.open(image) as handle:
                    handle.verify()
            except (UnidentifiedImageError, OSError):
                errors.append(f"{split}/{image.name}: undecodable image")
            if image.stem not in labels:
                errors.append(f"{split}/{image.name}: missing label file")
                continue
            text = (root / "labels" / split / f"{image.stem}.txt").read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if problem := check_label_line(line, len(names)):
                    errors.append(f"{split}/{image.stem}.txt:{number}: {problem}")
                else:
                    instances[names[int(line.split()[0])]] += 1
        report[split] = {"images": len(images), "instances": {n: instances[n] for n in names}}
        for name in names:
            if instances[name] < MIN_INSTANCES_WARNING[split]:
                warnings.append(f"{split}: {name} has only {instances[name]} instances")

    for index, first in enumerate(SPLITS):
        for second in SPLITS[index + 1 :]:
            if shared := digests[first] & digests[second]:
                errors.append(f"{len(shared)} identical images shared by {first} and {second}")

    summary = {"splits": report, "warnings": warnings, "errors": errors[:50], "error_count": len(errors)}
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
