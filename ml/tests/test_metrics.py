import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.metrics import ap_per_class, box_iou, compute_ap, confusion_matrix, match_predictions


def test_box_iou():
    a = np.array([[0, 0, 2, 2]], float)
    b = np.array([[1, 1, 3, 3], [0, 0, 2, 2]], float)
    assert np.allclose(box_iou(a, b), [[1 / 7, 1.0]])


def test_perfect_predictions_score_one():
    gt = np.array([[0, 0, 1, 1], [2, 2, 3, 3]], float)
    cls = np.array([0, 1])
    tp = match_predictions(gt, cls, gt, cls)
    metrics = ap_per_class(tp, np.array([0.9, 0.8]), cls, cls, num_classes=2)
    assert metrics[0].ap50 > 0.99 and metrics[1].ap50_95 > 0.99


def test_wrong_class_is_not_a_match():
    gt = np.array([[0, 0, 1, 1]], float)
    tp = match_predictions(gt, np.array([1]), gt, np.array([0]))
    assert not tp.any()


def test_each_ground_truth_matches_once():
    gt = np.array([[0, 0, 1, 1]], float)
    preds = np.array([[0, 0, 1, 1], [0, 0, 1, 1.01]], float)
    tp = match_predictions(preds, np.array([0, 0]), gt, np.array([0]))
    assert tp[:, 0].sum() == 1


def test_half_recall_with_perfect_precision():
    # Ultralytics-style interpolation: precision 1 up to recall 0.5, then linear to 0 at recall 1.
    gt = np.array([[0, 0, 1, 1], [2, 2, 3, 3]], float)
    preds = gt[:1]
    tp = match_predictions(preds, np.array([0]), gt, np.array([0, 0]))
    metrics = ap_per_class(tp, np.array([0.9]), np.array([0]), np.array([0, 0]), num_classes=1)
    assert abs(metrics[0].ap50 - 0.75) < 0.01
    assert metrics[0].recall == 0.5 and metrics[0].precision == 1.0


def test_compute_ap_bounds():
    assert compute_ap(np.array([1.0]), np.array([1.0])) > 0.99
    assert compute_ap(np.array([0.0]), np.array([0.0])) < 0.01


def test_presence_metrics_and_baseline():
    from ecorevive_ml.metrics import best_presence_threshold, presence_metrics

    has = np.array([True, True, True, False])
    scores = np.array([0.9, 0.6, 0.2, 0.7])
    m = presence_metrics(has, scores, 0.5)
    assert m["counts"] == {"tp": 2, "tn": 0, "fp": 1, "fn": 1}
    assert m["accuracy"] == 0.5 and m["majority_baseline_accuracy"] == 0.75
    assert 0.6 < best_presence_threshold(has, scores) <= 0.9


def test_confusion_matrix_counts_misses_and_false_positives():
    gt = np.array([[0, 0, 1, 1], [5, 5, 6, 6]], float)
    preds = np.array([[0, 0, 1, 1], [9, 9, 10, 10]], float)
    matrix = confusion_matrix(preds, np.array([1, 0]), np.array([0.9, 0.9]), gt, np.array([0, 1]), num_classes=2)
    assert matrix[1, 0] == 1  # predicted 1, truly 0
    assert matrix[2, 1] == 1  # missed ground truth of class 1
    assert matrix[0, 2] == 1  # false positive of class 0
