"""Photo-level accuracy of the deployed system: YOLO detector, Gemini vision check, and combinations.

Question scored: "does this photo contain plastic?". A photo counts as plastic when its labels
contain at least one Plastic box. Every rule is reported with accuracy, balanced accuracy and the
"always plastic" baseline, so class imbalance cannot inflate the score.

Rules (YOLO score = highest Plastic confidence in the photo):
  yolo@T          plastic if YOLO score >= T
  gemini          plastic if Gemini vision says the photo contains plastic
  yolo_or_gemini  plastic if either says so
  yolo_and_gemini plastic if both say so
  gated           YOLO decides when it is sure (score >= HIGH or < LOW), Gemini decides otherwise

Gemini answers are cached in ml/reports/hybrid/<split>_gemini.jsonl, so each photo is asked once.
The rule and thresholds must be chosen on val. The test split is locked: it needs
--confirm-locked-test and the run is appended to ml/reports/hybrid/test_ledger.jsonl.

  backend/.venv/Scripts/python ml/scripts/evaluate_hybrid.py --split val
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.detector import OnnxDetector  # noqa: E402
from app.vision import PHOTO_PROMPT, PhotoVerdict  # noqa: E402

CLASSES = ["Plastic", "Glass", "Metal", "Organic", "Hazardous"]
REPORTS = ROOT / "ml" / "reports" / "hybrid"


def has_plastic(label: Path) -> bool:
    if not label.exists():
        return False
    return any(line.split()[0] == "0" for line in label.read_text(encoding="utf-8").splitlines() if line.strip())


def jpeg_b64(path: Path, side: int = 768) -> str:
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    image.thumbnail((side, side))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


async def ask_gemini(photos: list[Path], cache_path: Path, model: str, key: str, workers: int) -> dict[str, dict]:
    from google import genai

    cache: dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            cache[row["photo"]] = row
    todo = [p for p in photos if p.name not in cache]
    print(f"Gemini: {len(cache)} cached, {len(todo)} to ask ({model})")
    client = genai.Client(api_key=key)
    semaphore = asyncio.Semaphore(workers)
    lock = asyncio.Lock()

    async def one(photo: Path) -> None:
        async with semaphore:
            for attempt in range(5):
                try:
                    reply = await client.aio.interactions.create(
                        model=model,
                        input=[{"type": "text", "text": PHOTO_PROMPT},
                               {"type": "image", "data": jpeg_b64(photo), "mime_type": "image/jpeg"}],
                        response_format={"type": "text", "mime_type": "application/json",
                                         "schema": PhotoVerdict.model_json_schema()},
                        timeout=30,
                    )
                    verdict = PhotoVerdict.model_validate_json(reply.output_text)
                    break
                except Exception as exc:  # rate limits and transient errors: back off and retry
                    if attempt == 4:
                        print("  failed", photo.name, type(exc).__name__)
                        return
                    await asyncio.sleep(2 * 2**attempt)
            row = {"photo": photo.name, **verdict.model_dump()}
            async with lock:
                cache[photo.name] = row
                with cache_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                if len(cache) % 25 == 0:
                    print(f"  {len(cache)}/{len(photos)}")

    await asyncio.gather(*(one(p) for p in todo))
    return cache


def score(pred: np.ndarray, truth: np.ndarray) -> dict:
    tp = int(np.sum(pred & truth))
    tn = int(np.sum(~pred & ~truth))
    recall = tp / max(1, int(truth.sum()))
    specificity = tn / max(1, int((~truth).sum()))
    return {
        "accuracy": round(float(np.mean(pred == truth)), 4),
        "balanced_accuracy": round((recall + specificity) / 2, 4),
        "finds_plastic": round(recall, 4),
        "correct_no_plastic": round(specificity, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=ROOT / "ml/data/processed/taco-5class-v1")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "backend/models/current")
    parser.add_argument("--split", choices=["val", "test"], default="val")
    parser.add_argument("--confirm-locked-test", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rule", help="Rule chosen on val, recorded in the test ledger")
    args = parser.parse_args()
    if args.split == "test" and not (args.confirm_locked_test and args.rule):
        sys.exit("The test split is locked. Choose the rule on val, then pass --rule and --confirm-locked-test.")

    settings = Settings()
    if not settings.gemini_api_key:
        sys.exit("GEMINI_API_KEY is not set (backend/.env).")
    photos = sorted((args.data / "images" / args.split).glob("*.jpg"))
    if not photos:
        sys.exit(f"No photos in {args.data / 'images' / args.split}")
    truth = np.array([has_plastic(args.data / "labels" / args.split / f"{p.stem}.txt") for p in photos])

    detector = OnnxDetector(args.model_dir, CLASSES, 0.01, 0.45, 100, 4)
    yolo = []
    for p in photos:
        image = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        dets = [d.confidence for d in detector.predict(image) if d.class_id == 0]
        yolo.append(max(dets, default=0.0))
    yolo_score = np.array(yolo)

    REPORTS.mkdir(parents=True, exist_ok=True)
    cache = asyncio.run(ask_gemini(photos, REPORTS / f"{args.split}_gemini.jsonl", settings.gemini_model,
                                   settings.gemini_api_key.get_secret_value(), args.workers))
    answered = np.array([p.name in cache for p in photos])
    gem = np.array([bool(cache.get(p.name, {}).get("contains_plastic", False)) for p in photos])

    rules: dict[str, np.ndarray] = {}
    for t in (0.1, 0.14, 0.2, 0.25, 0.3):
        rules[f"yolo@{t}"] = yolo_score >= t
    rules["gemini"] = gem
    rules["yolo@0.25_or_gemini"] = (yolo_score >= 0.25) | gem
    rules["yolo@0.25_and_gemini"] = (yolo_score >= 0.25) & gem
    for high in (0.4, 0.5, 0.6):
        for low in (0.05, 0.1):
            rules[f"gated_{low}_{high}"] = np.where(yolo_score >= high, True, np.where(yolo_score < low, False, gem))

    report = {
        "split": args.split,
        "photos": len(photos),
        "with_plastic": int(truth.sum()),
        "gemini_answered": int(answered.sum()),
        "always_plastic_baseline": round(float(truth.mean()), 4),
        "model_version": detector.version,
        "gemini_model": settings.gemini_model,
        "rules": {name: score(pred, truth) for name, pred in rules.items()},
    }
    print(json.dumps({k: v for k, v in report.items() if k != "rules"}, indent=2))
    print(f"{'rule':28} {'acc':>7} {'bal':>7} {'finds':>7} {'no-pl':>7}")
    for name, s in report["rules"].items():
        print(f"{name:28} {s['accuracy']:7.1%} {s['balanced_accuracy']:7.1%} "
              f"{s['finds_plastic']:7.1%} {s['correct_no_plastic']:7.1%}")
    out = REPORTS / f"{args.split}_report.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.split == "test":
        entry = {"evaluated_at": datetime.now(UTC).isoformat(), "rule": args.rule,
                 "result": report["rules"].get(args.rule), "baseline": report["always_plastic_baseline"],
                 "model_version": detector.version, "gemini_model": settings.gemini_model}
        with (REPORTS / "test_ledger.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        print("Ledger:", json.dumps(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
