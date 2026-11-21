"""Build the versioned 5-class YOLO dataset from TACO with leakage-safe splits and a manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import imagehash
import yaml
from PIL import Image, ImageOps, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.labels import canonical_names, coco_box_to_yolo, load_mapping
from ecorevive_ml.splits import (
    SPLITS,
    assign_groups,
    near_duplicate_pairs,
    overlap_report,
    resolve_cross_split_duplicates,
)

DATASET_VERSION = "taco-5class-v1"
ASPECT_TOLERANCE = 0.02
MAX_IMAGE_SIDE = 640


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("ml/data/raw/taco"))
    parser.add_argument("--out", type=Path, default=Path(f"ml/data/processed/{DATASET_VERSION}"))
    parser.add_argument("--manifest-dir", type=Path, default=Path("ml/manifests"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out-of-scope-only",
        choices=["keep", "drop"],
        default="keep",
        help="Photos whose only objects are out of scope (paper, cartons, cigarettes...). 'keep' uses them as "
        "negatives so the detector learns these are not plastic/glass/metal; 'drop' removes them.",
    )
    args = parser.parse_args()

    names = canonical_names()
    mapping = load_mapping(names=names)
    annotations_path = args.raw / "annotations.json"
    coco = json.loads(annotations_path.read_text(encoding="utf-8"))
    category_names = {c["id"]: c["name"] for c in coco["categories"]}
    mapping.validate_covers(list(category_names.values()))

    by_image: dict[int, list[dict]] = defaultdict(list)
    for annotation in coco["annotations"]:
        by_image[annotation["image_id"]].append(annotation)

    excluded: Counter = Counter()
    records: dict[str, dict] = {}
    hashes: dict[str, int] = {}

    for image in coco["images"]:
        key = image["file_name"]
        path = args.raw / "images" / key
        anns = by_image[image["id"]]
        if any(category_names[a["category_id"]] in mapping.ambiguous for a in anns):
            excluded["ambiguous_label"] += 1
            continue
        if not path.exists():
            excluded["missing_file"] += 1
            continue
        try:
            with Image.open(path) as handle:
                decoded = ImageOps.exif_transpose(handle).convert("RGB")
        except (UnidentifiedImageError, OSError):
            excluded["undecodable"] += 1
            continue

        expected = image["width"] / image["height"]
        actual = decoded.width / decoded.height
        if abs(actual - expected) / expected > ASPECT_TOLERANCE:
            excluded["orientation_mismatch"] += 1
            continue
        decoded.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))

        labels = []
        for annotation in anns:
            class_id = mapping.to_class_id.get(category_names[annotation["category_id"]])
            if class_id is None:
                continue
            box = coco_box_to_yolo(annotation["bbox"], image["width"], image["height"])
            if box is None:
                excluded["degenerate_box"] += 1
                continue
            labels.append((class_id, *box))

        if not labels and anns:
            excluded["out_of_scope_only_kept" if args.out_of_scope_only == "keep" else "out_of_scope_only_dropped"] += 1
            if args.out_of_scope_only == "drop":
                continue
        records[key] = {
            "image": decoded,
            "labels": labels,
            "batch": key.split("/")[0],
            "license": image.get("license") or "TACO (per-image terms, see docs/DATASET.md)",
        }
        hashes[key] = int(str(imagehash.phash(decoded)), 16)

    group_sizes: Counter = Counter()
    group_counts: dict[str, Counter] = defaultdict(Counter)
    for record in records.values():
        group_sizes[record["batch"]] += 1
        group_counts[record["batch"]].update(label[0] for label in record["labels"])

    assignment = assign_groups(dict(group_sizes), dict(group_counts), list(range(len(names))), args.seed)
    image_split = {key: assignment[record["batch"]] for key, record in records.items()}
    pairs = near_duplicate_pairs(hashes)
    moved = resolve_cross_split_duplicates(image_split, pairs)
    moved_count = sum(1 for key in moved if moved[key] != image_split[key])
    image_split = moved
    remaining = overlap_report(image_split, pairs)
    if remaining:
        raise RuntimeError(f"{len(remaining)} near-duplicate pairs still cross splits.")

    if args.out.exists():
        shutil.rmtree(args.out)
    manifest_rows = []
    split_stats = {s: {"images": 0, "backgrounds": 0, "instances": Counter()} for s in SPLITS}
    for key in sorted(records):
        record, split = records[key], image_split[key]
        stem = key.replace("/", "_").rsplit(".", 1)[0]
        image_path = args.out / "images" / split / f"{stem}.jpg"
        label_path = args.out / "labels" / split / f"{stem}.txt"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.parent.mkdir(parents=True, exist_ok=True)
        record["image"].save(image_path, "JPEG", quality=95)
        lines = [f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}" for c, x, y, w, h in record["labels"]]
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        stats = split_stats[split]
        stats["images"] += 1
        stats["backgrounds"] += 0 if lines else 1
        stats["instances"].update(names[label[0]] for label in record["labels"])
        manifest_rows.append(
            {
                "source": key,
                "split": split,
                "batch": record["batch"],
                "license": record["license"],
                "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "phash": f"{hashes[key]:016x}",
                "instances": len(lines),
            }
        )

    data_yaml = {
        "path": str(args.out.resolve()).replace("\\", "/"),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(names)),
    }
    (args.out / "data.yaml").write_text(yaml.safe_dump(data_yaml, sort_keys=False), encoding="utf-8")

    summary = {
        "dataset_version": DATASET_VERSION,
        "mapping_version": mapping.version,
        "seed": args.seed,
        "out_of_scope_only": args.out_of_scope_only,
        "annotations_sha256": hashlib.sha256(annotations_path.read_bytes()).hexdigest(),
        "source_commit": (args.raw / "SOURCE_COMMIT.txt").read_text(encoding="utf-8").strip(),
        "batch_assignment": dict(sorted(assignment.items())),
        "excluded_images": dict(excluded),
        "image_licenses": dict(Counter(r["license"] for r in records.values())),
        "near_duplicate_pairs": len(pairs),
        "images_moved_to_train_for_duplicates": moved_count,
        "splits": {
            s: {
                "images": v["images"],
                "backgrounds": v["backgrounds"],
                "instances": {n: v["instances"][n] for n in names},
            }
            for s, v in split_stats.items()
        },
    }
    args.manifest_dir.mkdir(parents=True, exist_ok=True)
    (args.manifest_dir / f"{DATASET_VERSION}.summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (args.manifest_dir / f"{DATASET_VERSION}.manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in manifest_rows), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
