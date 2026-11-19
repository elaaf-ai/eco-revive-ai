"""Build taco-5class-v2: v1 plus cleaned TrashNet photos from the Roboflow export, train split only.

Validation and the locked test split are copied unchanged from v1, so v2 is compared with v1 on the
same images. Extra photos are read straight from the ZIP, grouped by original photo (Roboflow
augmented copies share a source name), filtered for label consistency, and dropped if they look
like a near-duplicate of any validation or test photo.

  python ml/scripts/prepare_v2.py --roboflow-zip <taco-trashnet-current.v1i.yolov11.zip>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import imagehash
import yaml
from PIL import Image, ImageOps, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.labels import canonical_names  # noqa: E402
from ecorevive_ml.splits import hamming  # noqa: E402

V1 = Path("ml/data/processed/taco-5class-v1")
OUT = Path("ml/data/processed/taco-5class-v2")
DATASET_VERSION = "taco-5class-v2"
MAX_SIDE = 640
SOURCE_RE = re.compile(r"^(?P<src>.+?)_(?:jpg|jpeg|png)\.rf\.[0-9a-f]+\.(?:jpg|jpeg|png)$", re.IGNORECASE)


def source_name(file_name: str) -> str:
    match = SOURCE_RE.match(file_name)
    return match.group("src") if match else Path(file_name).stem


def prefix_of(source: str) -> str:
    match = re.match(r"[A-Za-z]+", source)
    return match.group(0).lower() if match else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--roboflow-zip", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("ml/configs/roboflow_mapping_v2.yaml"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    names = canonical_names()
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    src_classes = cfg["source_classes"]
    rng = random.Random(args.seed)

    # Perceptual hashes of every v1 val/test image, to keep the holdouts clean.
    holdout_hashes = []
    for split in ("val", "test"):
        for path in sorted((V1 / "images" / split).glob("*.jpg")):
            with Image.open(path) as handle:
                holdout_hashes.append(int(str(imagehash.phash(handle.convert("RGB"))), 16))

    excluded: Counter = Counter()
    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)  # source -> [(image member, label member)]
    archive = zipfile.ZipFile(args.roboflow_zip)
    members = set(archive.namelist())
    for member in sorted(members):
        parts = member.split("/")
        if len(parts) != 3 or parts[1] != "images":
            continue
        label = f"{parts[0]}/labels/{Path(parts[2]).stem}.txt"
        candidates[source_name(parts[2])].append((member, label if label in members else ""))

    kept: dict[str, dict] = {}
    background_sources = []
    for source, copies in sorted(candidates.items()):
        prefix = prefix_of(source)
        known = prefix in cfg["labelled"] or prefix in cfg["background"]["prefixes"]
        if prefix in cfg["excluded_prefixes"] or not known:
            excluded[f"prefix:{prefix or 'none'}"] += len(copies)
            continue
        rule = cfg["labelled"].get(prefix)
        expect = rule["expect"] if rule else cfg["background"]["expect"]
        consistent = True
        for _, label in copies:
            lines = archive.read(label).decode().split("\n") if label else []
            classes = {src_classes[int(line.split()[0])] for line in lines if line.strip()}
            if not classes or classes != {expect}:
                consistent = False
                break
        if not consistent:
            excluded["inconsistent_labels"] += len(copies)
            continue
        if rule:
            kept[source] = {"copies": copies, "to": names.index(rule["to"]), "prefix": prefix}
        else:
            background_sources.append(source)

    rng.shuffle(background_sources)
    for source in background_sources[: cfg["background"]["max_images"]]:
        kept[source] = {"copies": candidates[source][:1], "to": None, "prefix": prefix_of(source)}
    over_cap = background_sources[cfg["background"]["max_images"]:]
    excluded["background_over_cap"] = sum(len(candidates[s]) for s in over_cap)

    if OUT.exists():
        shutil.rmtree(OUT)
    for split in ("train", "val", "test"):
        shutil.copytree(V1 / "images" / split, OUT / "images" / split)
        shutil.copytree(V1 / "labels" / split, OUT / "labels" / split)

    added_instances: Counter = Counter()
    added_images = 0
    rows = []
    for source, info in sorted(kept.items()):
        for image_member, label_member in info["copies"]:
            try:
                with Image.open(io.BytesIO(archive.read(image_member))) as handle:
                    image = ImageOps.exif_transpose(handle).convert("RGB")
            except (UnidentifiedImageError, OSError):
                excluded["undecodable"] += 1
                continue
            phash = int(str(imagehash.phash(image)), 16)
            if any(hamming(phash, h) <= cfg["near_duplicate_max_distance"] for h in holdout_hashes):
                excluded["near_duplicate_of_holdout"] += 1
                continue
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            stem = "rf_" + Path(image_member).stem.replace(".", "_")
            image_path = OUT / "images" / "train" / f"{stem}.jpg"
            image.save(image_path, "JPEG", quality=92)
            lines = []
            if info["to"] is not None:
                for line in archive.read(label_member).decode().splitlines():
                    if line.strip():
                        _, x, y, w, h = line.split()
                        lines.append(f"{info['to']} {x} {y} {w} {h}")
                        added_instances[names[info["to"]]] += 1
            (OUT / "labels" / "train" / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""),
                                                                  encoding="utf-8")
            added_images += 1
            rows.append({"file": image_path.name, "source": source, "origin": "roboflow:" + image_member,
                         "class": names[info["to"]] if info["to"] is not None else "background",
                         "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest()})

    data = {"path": str(OUT.resolve()).replace("\\", "/"), "train": "images/train", "val": "images/val",
            "test": "images/test", "names": dict(enumerate(names))}
    (OUT / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    summary = {
        "dataset_version": DATASET_VERSION,
        "base": "taco-5class-v1 (val and test unchanged)",
        "extra_source": "Roboflow taco-trashnet-current v1 (CC BY 4.0), TrashNet-origin photos only",
        "mapping_version": cfg["version"],
        "seed": args.seed,
        "roboflow_zip_sha256": hashlib.sha256(args.roboflow_zip.read_bytes()).hexdigest(),
        "extra_sources_kept": len(kept),
        "extra_train_images_added": added_images,
        "extra_instances_added": dict(added_instances),
        "excluded": dict(excluded),
    }
    Path("ml/manifests").mkdir(exist_ok=True)
    Path(f"ml/manifests/{DATASET_VERSION}.summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                                                    encoding="utf-8")
    Path(f"ml/manifests/{DATASET_VERSION}.extra.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
