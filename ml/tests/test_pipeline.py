import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.labels import (
    MAPPING_PATH,
    canonical_names,
    coco_box_to_yolo,
    load_mapping,
)
from ecorevive_ml.splits import (
    assign_groups,
    near_duplicate_pairs,
    overlap_report,
    resolve_cross_split_duplicates,
)


def test_canonical_classes_are_the_five_project_classes():
    assert canonical_names() == ["Plastic", "Glass", "Metal", "Organic", "Hazardous"]


def test_canonical_names_reject_id_gaps(tmp_path):
    path = tmp_path / "classes.json"
    path.write_text(json.dumps({"classes": [{"id": 0, "name": "A"}, {"id": 2, "name": "B"}]}))
    with pytest.raises(ValueError):
        canonical_names(path)


def test_mapping_assigns_safety_relevant_categories_explicitly():
    mapping = load_mapping()
    names = canonical_names()
    assert names[mapping.to_class_id["Battery"]] == "Hazardous"
    assert names[mapping.to_class_id["Aerosol"]] == "Hazardous"
    assert names[mapping.to_class_id["Broken glass"]] == "Glass"
    assert "Unlabeled litter" in mapping.ambiguous
    assert "Cigarette" in mapping.out_of_scope


def test_mapping_rejects_category_listed_twice(tmp_path):
    text = MAPPING_PATH.read_text(encoding="utf-8").replace("  Glass:\n", "  Glass:\n    - Battery\n")
    path = tmp_path / "mapping.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_mapping(path)


def test_mapping_coverage_detects_unmapped_category():
    mapping = load_mapping()
    categories = [*mapping.to_class_id, *mapping.out_of_scope, *mapping.ambiguous, "New category"]
    with pytest.raises(ValueError):
        mapping.validate_covers(categories)


def test_coco_box_is_normalized_and_clipped():
    assert coco_box_to_yolo([0, 0, 50, 100], 100, 200) == (0.25, 0.25, 0.5, 0.5)
    assert coco_box_to_yolo([-10, 0, 20, 100], 100, 100) == (0.05, 0.5, 0.1, 1.0)
    assert coco_box_to_yolo([99.9, 0, 5, 5], 100, 100) is None


def test_group_assignment_is_deterministic_and_keeps_groups_whole():
    sizes = {f"batch_{i}": 100 for i in range(10)}
    counts = {f"batch_{i}": Counter({0: 5, 1: 2}) for i in range(10)}
    first = assign_groups(sizes, counts, [0, 1], seed=42, trials=500)
    assert first == assign_groups(sizes, counts, [0, 1], seed=42, trials=500)
    assert set(first) == set(sizes)
    assert set(first.values()) == {"train", "val", "test"}


def test_rare_class_is_not_starved_in_training():
    sizes = {f"batch_{i}": 100 for i in range(10)}
    counts = {f"batch_{i}": Counter({0: 10, 1: 1}) for i in range(10)}
    assignment = assign_groups(sizes, counts, [0, 1], seed=42, trials=2000)
    train_rare = sum(counts[g][1] for g, split in assignment.items() if split == "train")
    assert train_rare >= 6


def test_near_duplicates_crossing_splits_move_to_train():
    split = {"a": "train", "b": "test", "c": "val", "d": "test"}
    hashes = {"a": 0b1111, "b": 0b1110, "c": (2**20 - 1) << 20, "d": (2**20 - 1) << 40}
    pairs = near_duplicate_pairs(hashes, max_distance=2)
    assert pairs == [("a", "b")]
    resolved = resolve_cross_split_duplicates(split, pairs)
    assert resolved["b"] == "train"
    assert resolved["c"] == "val"
    assert overlap_report(resolved, pairs) == []


def test_duplicate_chain_moves_as_one_cluster():
    split = {"a": "train", "b": "val", "c": "test"}
    resolved = resolve_cross_split_duplicates(split, [("a", "b"), ("b", "c")])
    assert set(resolved.values()) == {"train"}
