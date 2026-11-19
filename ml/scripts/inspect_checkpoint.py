"""Verify a checkpoint's classes against the canonical list and optionally run sample inference.

Exit codes: 0 compatible, 2 class mismatch. Only load checkpoints from trusted sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.labels import canonical_names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--samples", type=Path, default=None, help="Folder of sample images")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    model = YOLO(str(args.weights))
    names = [model.names[i] for i in sorted(model.names)]
    expected = canonical_names()
    report = {
        "weights": str(args.weights),
        "sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "classes": names,
        "expected": expected,
        "compatible": names == expected,
    }

    if args.samples:
        images = sorted(p for p in args.samples.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        report["samples"] = [
            {
                "image": path.name,
                "detections": [
                    {"class": names[int(box.cls)], "confidence": round(float(box.conf), 3)}
                    for box in model.predict(str(path), imgsz=640, verbose=False)[0].boxes
                ],
            }
            for path in images[: args.limit]
        ]

    print(json.dumps(report, indent=2))
    return 0 if report["compatible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
