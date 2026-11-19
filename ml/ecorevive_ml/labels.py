"""Canonical classes and the versioned TACO label mapping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASSES_PATH = REPO_ROOT / "shared" / "classes.json"
MAPPING_PATH = REPO_ROOT / "ml" / "configs" / "taco_mapping_v1.yaml"


def canonical_names(path: Path = CLASSES_PATH) -> list[str]:
    """Return class names ordered by class id, rejecting gaps or duplicates."""
    classes = json.loads(path.read_text(encoding="utf-8"))["classes"]
    ordered = sorted(classes, key=lambda c: c["id"])
    if [c["id"] for c in ordered] != list(range(len(ordered))):
        raise ValueError("Class ids must be contiguous and start at 0.")
    names = [c["name"] for c in ordered]
    if len(set(names)) != len(names):
        raise ValueError("Class names must be unique.")
    return names


@dataclass(frozen=True)
class TacoMapping:
    version: str
    to_class_id: dict[str, int]
    out_of_scope: frozenset[str]
    ambiguous: frozenset[str]

    def validate_covers(self, taco_categories: list[str]) -> None:
        """Fail if any TACO category has no explicit rule, or a rule names an unknown category."""
        known = set(self.to_class_id) | self.out_of_scope | self.ambiguous
        missing = sorted(set(taco_categories) - known)
        unknown = sorted(known - set(taco_categories))
        if missing or unknown:
            raise ValueError(f"Mapping mismatch. Unmapped: {missing}. Unknown: {unknown}.")


def load_mapping(path: Path = MAPPING_PATH, names: list[str] | None = None) -> TacoMapping:
    """Load the mapping and reject categories assigned to more than one rule."""
    names = names or canonical_names()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if set(raw["classes"]) != set(names):
        raise ValueError(f"Mapping classes {sorted(raw['classes'])} differ from canonical {names}.")

    to_class_id: dict[str, int] = {}
    for class_name, categories in raw["classes"].items():
        for category in categories:
            if category in to_class_id:
                raise ValueError(f"Category mapped twice: {category}")
            to_class_id[category] = names.index(class_name)

    out_of_scope = frozenset(raw["out_of_scope"])
    ambiguous = frozenset(raw["ambiguous_exclude_image"])
    overlap = (set(to_class_id) & (out_of_scope | ambiguous)) | (out_of_scope & ambiguous)
    if overlap:
        raise ValueError(f"Categories appear under several rules: {sorted(overlap)}")
    return TacoMapping(raw["version"], to_class_id, out_of_scope, ambiguous)


def coco_box_to_yolo(box: list[float], width: float, height: float) -> tuple[float, float, float, float] | None:
    """Convert a COCO [x, y, w, h] box to normalized YOLO, clipped to the image. None if degenerate."""
    x, y, w, h = box
    x1, y1 = max(0.0, x), max(0.0, y)
    x2, y2 = min(width, x + w), min(height, y + h)
    if x2 - x1 < 1 or y2 - y1 < 1:
        return None
    return (
        (x1 + x2) / 2 / width,
        (y1 + y2) / 2 / height,
        (x2 - x1) / width,
        (y2 - y1) / height,
    )
