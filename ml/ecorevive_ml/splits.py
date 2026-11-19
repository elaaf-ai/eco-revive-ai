"""Leakage-safe dataset splitting: whole collection sessions go to exactly one split."""

from __future__ import annotations

import random
from collections import Counter, defaultdict

SPLITS = ("train", "val", "test")


def assign_groups(
    group_sizes: dict[str, int],
    group_class_counts: dict[str, Counter],
    class_ids: list[int],
    seed: int,
    val_fraction: float = 0.15,
    test_fraction: float = 0.15,
    trials: int = 20000,
) -> dict[str, str]:
    """Assign each group to a split, favouring class coverage in val and test, then size balance.

    The search uses label counts only, never model output, and is deterministic for a seed.
    """
    groups = sorted(group_sizes)
    if len(groups) < 3:
        raise ValueError("At least three groups are needed for train, val and test.")
    total = sum(group_sizes.values())
    rng = random.Random(seed)
    best: dict[str, str] | None = None
    best_score: tuple[float, ...] | None = None

    for _ in range(trials):
        order = groups[:]
        rng.shuffle(order)
        n_val = rng.randint(1, max(1, len(groups) // 3))
        n_test = rng.randint(1, max(1, len(groups) // 3))
        if n_val + n_test >= len(groups):
            continue
        assignment = {g: "val" for g in order[:n_val]}
        assignment |= {g: "test" for g in order[n_val : n_val + n_test]}
        assignment |= {g: "train" for g in order[n_val + n_test :]}

        counts = {s: Counter() for s in SPLITS}
        sizes: Counter = Counter()
        for group, split in assignment.items():
            counts[split].update(group_class_counts[group])
            sizes[split] += group_sizes[group]

        covered = sum(1 for s in SPLITS for c in class_ids if counts[s][c] > 0)
        # Compare each split's share of a class with its intended share, so rare classes
        # are not starved in training in exchange for holdout coverage.
        train_fraction = 1 - val_fraction - test_fraction
        targets = {"train": train_fraction, "val": val_fraction, "test": test_fraction}
        rarest = min(counts[s][c] / targets[s] for s in SPLITS for c in class_ids)
        balance = abs(sizes["val"] / total - val_fraction) + abs(sizes["test"] / total - test_fraction)
        score = (covered, rarest, -round(balance, 6))
        if best_score is None or score > best_score:
            best, best_score = assignment, score

    assert best is not None
    return best


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def near_duplicate_pairs(hashes: dict[str, int], max_distance: int = 4) -> list[tuple[str, str]]:
    """Return image pairs whose 64-bit perceptual hashes differ by at most max_distance bits."""
    keys = sorted(hashes)
    return [
        (a, b)
        for i, a in enumerate(keys)
        for b in keys[i + 1 :]
        if hamming(hashes[a], hashes[b]) <= max_distance
    ]


def resolve_cross_split_duplicates(
    image_split: dict[str, str], pairs: list[tuple[str, str]]
) -> dict[str, str]:
    """Move every connected duplicate cluster spanning splits into train, keeping holdouts clean."""
    parent = {k: k for k in image_split}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)

    clusters: dict[str, list[str]] = defaultdict(list)
    for key in image_split:
        clusters[find(key)].append(key)

    resolved = dict(image_split)
    for members in clusters.values():
        if len({image_split[m] for m in members}) > 1:
            for member in members:
                resolved[member] = "train"
    return resolved


def overlap_report(image_split: dict[str, str], pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Return duplicate pairs that still cross split boundaries. Must be empty before training."""
    return [(a, b) for a, b in pairs if image_split[a] != image_split[b]]
