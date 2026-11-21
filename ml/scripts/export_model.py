"""Export best.pt to ONNX and TFLite, compare each against the checkpoint, and record checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.labels import canonical_names

IOU_MATCH = 0.9
CONF_TOLERANCE = 0.05
PAD_VALUE = 114


def square_letterbox(sources: list[Path], out_dir: Path, size: int) -> list[Path]:
    """Write size x size letterboxed copies, the input shape the web API and Android app use.

    best.pt pads only to a multiple of 32 while fixed-shape exports pad to a full square, so
    parity must feed both models identical, already-square images.
    """
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for source in sources:
        image = cv2.imread(str(source))
        height, width = image.shape[:2]
        scale = min(size / height, size / width)
        new_w, new_h = round(width * scale), round(height * scale)
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((size, size, 3), PAD_VALUE, dtype=np.uint8)
        top, left = (size - new_h) // 2, (size - new_w) // 2
        canvas[top : top + new_h, left : left + new_w] = resized
        target = out_dir / f"{source.stem}.png"
        cv2.imwrite(str(target), canvas)
        written.append(target)
    return written


def iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return float(overlap / union) if union > 0 else 0.0


def detections(model: YOLO, image: Path, imgsz: int) -> list[tuple[int, float, np.ndarray]]:
    boxes = model.predict(str(image), imgsz=imgsz, conf=0.25, verbose=False)[0].boxes
    return [(int(b.cls), float(b.conf), b.xyxy[0].cpu().numpy()) for b in boxes]


def match_counts(a: list, b: list) -> tuple[int, list[float]]:
    """How many detections in a have a same-class detection in b with IoU >= IOU_MATCH."""
    matched, deltas = 0, []
    for class_id, conf, box in a:
        same_class = [o for o in b if o[0] == class_id]
        best = max(same_class, key=lambda o: iou(box, o[2]), default=None)
        if best is not None and iou(box, best[2]) >= IOU_MATCH:
            matched += 1
            deltas.append(abs(conf - best[1]))
    return matched, deltas


def parity(reference: YOLO, candidate: YOLO, images: list[Path], imgsz: int) -> dict:
    """Compare both ways: every reference box must appear in the export, and the export must not
    add boxes the reference does not have (extra false positives)."""
    ref_total = cand_total = ref_matched = cand_matched = 0
    conf_deltas: list[float] = []
    for image in images:
        ref = detections(reference, image, imgsz)
        cand = detections(candidate, image, imgsz)
        matched, deltas = match_counts(ref, cand)
        back, _ = match_counts(cand, ref)
        ref_total, cand_total = ref_total + len(ref), cand_total + len(cand)
        ref_matched, cand_matched = ref_matched + matched, cand_matched + back
        conf_deltas += deltas
    max_delta = max(conf_deltas, default=0.0)
    match_rate = ref_matched / ref_total if ref_total else 0.0
    reverse_rate = cand_matched / cand_total if cand_total else (1.0 if ref_total == 0 else 0.0)
    return {
        "images": len(images),
        "reference_detections": ref_total,
        "candidate_detections": cand_total,
        "matched": ref_matched,
        "match_rate": round(match_rate, 4),
        "candidate_matched_back": cand_matched,
        "reverse_match_rate": round(reverse_rate, 4),
        "extra_candidate_detections": cand_total - cand_matched,
        "max_confidence_delta": round(max_delta, 4),
        "passed": ref_total > 0 and match_rate >= 0.95 and reverse_rate >= 0.95 and max_delta <= CONF_TOLERANCE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--val-images", type=Path, required=True, help="Validation images for parity checks")
    parser.add_argument("--version", required=True, help="Model version, for example 0.1.0-preview")
    parser.add_argument("--formats", nargs="+", default=["onnx", "tflite"], choices=["onnx", "tflite"])
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--parity-images", type=int, default=50)
    parser.add_argument("--out", type=Path, default=Path("ml/artifacts"))
    args = parser.parse_args()

    reference = YOLO(str(args.weights))
    names = [reference.names[i] for i in sorted(reference.names)]
    if names != canonical_names():
        parser.error(f"Checkpoint classes {names} differ from canonical {canonical_names()}")

    target = args.out / args.version
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.weights, target / "best.pt")
    sources = sorted(args.val_images.glob("*.jpg"))[: args.parity_images]
    images = square_letterbox(sources, target / "parity_inputs", args.imgsz)

    manifest: dict = {"version": args.version, "classes": names, "imgsz": args.imgsz, "artifacts": {}}
    files = {"pt": target / "best.pt"}
    for fmt in args.formats:
        exported = Path(YOLO(str(args.weights)).export(format=fmt, imgsz=args.imgsz))
        destination = target / f"model.{fmt}"
        shutil.copy2(exported, destination)
        files[fmt] = destination
        candidate = YOLO(str(exported), task="detect")
        manifest.setdefault("parity", {})[fmt] = parity(reference, candidate, images, args.imgsz)

    for fmt, path in files.items():
        manifest["artifacts"][fmt] = {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0 if all(p["passed"] for p in manifest.get("parity", {}).values()) else 3


if __name__ == "__main__":
    raise SystemExit(main())
