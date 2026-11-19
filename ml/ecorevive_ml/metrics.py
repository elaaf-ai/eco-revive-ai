"""Detection metrics in NumPy, following the Ultralytics definitions.

Lets exported models (ONNX) be evaluated without PyTorch: 101-point interpolated AP at
IoU 0.50:0.05:0.95, mean over classes that have ground truth, and precision/recall at the
confidence that maximises mean F1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

IOU_THRESHOLDS = np.linspace(0.5, 0.95, 10)


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU between xyxy boxes a [N,4] and b [M,4]."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    tl = np.maximum(a[:, None, :2], b[None, :, :2])
    br = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.prod(np.clip(br - tl, 0, None), axis=2)
    area_a = np.prod(a[:, 2:] - a[:, :2], axis=1)
    area_b = np.prod(b[:, 2:] - b[:, :2], axis=1)
    return inter / (area_a[:, None] + area_b[None, :] - inter + 1e-12)


def match_predictions(
    pred_boxes: np.ndarray, pred_cls: np.ndarray, gt_boxes: np.ndarray, gt_cls: np.ndarray
) -> np.ndarray:
    """True-positive matrix [N_pred, 10]: one-to-one matching per IoU threshold, same class only."""
    tp = np.zeros((len(pred_boxes), len(IOU_THRESHOLDS)), dtype=bool)
    if len(pred_boxes) == 0 or len(gt_boxes) == 0:
        return tp
    iou = box_iou(gt_boxes, pred_boxes) * (gt_cls[:, None] == pred_cls[None, :])
    for t, threshold in enumerate(IOU_THRESHOLDS):
        gt_idx, pred_idx = np.nonzero(iou >= threshold)
        if len(gt_idx) == 0:
            continue
        order = iou[gt_idx, pred_idx].argsort()[::-1]
        gt_idx, pred_idx = gt_idx[order], pred_idx[order]
        _, first_pred = np.unique(pred_idx, return_index=True)
        gt_idx, pred_idx = gt_idx[first_pred], pred_idx[first_pred]
        order = iou[gt_idx, pred_idx].argsort()[::-1]
        gt_idx, pred_idx = gt_idx[order], pred_idx[order]
        _, first_gt = np.unique(gt_idx, return_index=True)
        tp[pred_idx[first_gt], t] = True
    return tp


def compute_ap(recall: np.ndarray, precision: np.ndarray) -> float:
    mrec = np.concatenate(([0.0], recall, [1.0]))
    mpre = np.concatenate(([1.0], precision, [0.0]))
    mpre = np.flip(np.maximum.accumulate(np.flip(mpre)))
    x = np.linspace(0, 1, 101)
    return float(np.trapezoid(np.interp(x, mrec, mpre), x))


@dataclass
class ClassMetrics:
    instances: int
    ap50: float
    ap50_95: float
    precision: float
    recall: float


def ap_per_class(
    tp: np.ndarray, conf: np.ndarray, pred_cls: np.ndarray, target_cls: np.ndarray, num_classes: int
) -> dict[int, ClassMetrics]:
    order = np.argsort(-conf)
    tp, conf, pred_cls = tp[order], conf[order], pred_cls[order]
    grid = np.linspace(0, 1, 1000)
    p_curves = np.zeros((num_classes, len(grid)))
    r_curves = np.zeros((num_classes, len(grid)))
    aps = np.zeros((num_classes, len(IOU_THRESHOLDS)))
    counts = np.bincount(target_cls.astype(int), minlength=num_classes)

    for c in range(num_classes):
        mask = pred_cls == c
        n_labels = counts[c]
        if mask.sum() == 0 or n_labels == 0:
            continue
        fpc = (1 - tp[mask]).cumsum(0)
        tpc = tp[mask].cumsum(0)
        recall = tpc / (n_labels + 1e-16)
        precision = tpc / (tpc + fpc)
        r_curves[c] = np.interp(-grid, -conf[mask], recall[:, 0], left=0)
        p_curves[c] = np.interp(-grid, -conf[mask], precision[:, 0], left=1)
        for j in range(len(IOU_THRESHOLDS)):
            aps[c, j] = compute_ap(recall[:, j], precision[:, j])

    present = [c for c in range(num_classes) if counts[c] > 0]
    f1 = 2 * p_curves * r_curves / (p_curves + r_curves + 1e-16)
    best = int(np.convolve(f1[present].mean(0), np.ones(3) / 3, mode="same").argmax()) if present else 0
    return {
        c: ClassMetrics(
            instances=int(counts[c]),
            ap50=float(aps[c, 0]),
            ap50_95=float(aps[c].mean()),
            precision=float(p_curves[c, best]),
            recall=float(r_curves[c, best]),
        )
        for c in range(num_classes)
    }


def confusion_matrix(
    pred_boxes: np.ndarray,
    pred_cls: np.ndarray,
    pred_conf: np.ndarray,
    gt_boxes: np.ndarray,
    gt_cls: np.ndarray,
    num_classes: int,
    conf: float = 0.25,
    iou_threshold: float = 0.45,
) -> np.ndarray:
    """[(C+1) x (C+1)] counts: rows are predicted class, columns true class; last index is background."""
    matrix = np.zeros((num_classes + 1, num_classes + 1), dtype=int)
    keep = pred_conf >= conf
    pred_boxes, pred_cls = pred_boxes[keep], pred_cls[keep]
    bg = num_classes
    if len(gt_boxes) == 0:
        for p in pred_cls:
            matrix[p, bg] += 1
        return matrix
    iou = box_iou(gt_boxes, pred_boxes)
    used_pred: set[int] = set()
    for g in np.argsort(-iou.max(axis=1) if iou.size else np.zeros(len(gt_boxes))):
        candidates = [p for p in np.argsort(-iou[g]) if iou[g, p] >= iou_threshold and p not in used_pred]
        if candidates:
            used_pred.add(candidates[0])
            matrix[pred_cls[candidates[0]], gt_cls[g]] += 1
        else:
            matrix[bg, gt_cls[g]] += 1
    for p in range(len(pred_cls)):
        if p not in used_pred:
            matrix[pred_cls[p], bg] += 1
    return matrix
