# Evaluation

The original target was **mAP@0.50 of at least 0.85 on the locked held-out test split.** After the product became plastic-only, the team set the target as **85% photo-level accuracy for "does this photo contain plastic?"**. Balanced accuracy and the "always plastic" baseline are reported next to it, so the score cannot be inflated by class imbalance. Only results measured on the locked test split count toward the target.

## Current live model: `0.2.0-preview-small` (YOLO11s, taco-5class-v2, trained on Kaggle T4)

**Selection:** among v1 small, v2 small and v2 nano, chosen on **validation only**. The locked test split was then run **once** (see `ml/reports/v2-small/test_ledger.jsonl`).

**Training:** 60 epochs (best epoch 47), 640 px, batch 16, seed 42, about 33 minutes on one Tesla T4. The data was v1 plus 1,487 cleaned TrashNet photos (train only).

### Validation (172 photos, 138 with plastic)

| Model | Plastic AP@0.50 | Photo accuracy @0.25 | Balanced accuracy @0.25 | Finds plastic | Correct "no plastic" |
|---|---|---|---|---|---|
| v1 small (`0.1.0-preview`) | 0.434 | 72.1% | 54.9% | 83% | 26% |
| **v2 small (selected)** | **0.467** | **80.2%** | **64.4%** | **91%** | **38%** |
| v2 nano | 0.488 | 73.8% | 54.9% | 86% | 24% |

The "always plastic" baseline on validation is 80.2%.

### Locked test (210 photos, 148 with plastic), v2 small, run once

| Measure | Result |
|---|---|
| Photo accuracy @0.25 (app setting) | **68.1%**. "Always plastic" baseline is 70.5% |
| Balanced accuracy @0.25 | **56.8%** |
| Photo accuracy @0.14 (threshold fixed on validation) | 72.4% (balanced 58.9%) |
| Plastic AP@0.50 / AP@0.50:0.95 | 0.353 / 0.275 (217 objects, recall 0.50) |
| Glass / Metal AP@0.50 | 0.024 / 0.116 |
| 5-class mAP@0.50 / @0.50:0.95 | 0.099 / 0.074 |
| Latency (ONNX, CPU, this laptop) | about 130 ms per image |

**The 85% target is not met.**
- The photo-level score is below the "always plastic" baseline on the test photos.
- The model rarely says "no plastic" correctly: it called 99 real plastic objects background and 129 background regions plastic.
- Glass and Metal improved on validation but not on the test photos. The added TrashNet photos are studio-style single objects, while the test photos are outdoor litter (TACO), so the extra data did not transfer.

**What would most likely raise it:** labelled photos taken the way the app is used, with hand-held items indoors and real bins, including many photos **without** plastic. The 4-person team test sheet is a good start for these.

**Export parity:** on identical 640×640 inputs, ONNX and TFLite match `best.pt` exactly (100% detections matched, confidence difference 0.0).

---

## Previous model: `0.1.0-preview`

## Current model: `0.1.0-preview` (YOLO11s, 640 px, trained in Colab on `taco-5class-v1`)

**Status:** measured on validation only. The locked test split has not been run, and the target is **not** met.

### Validation results (172 images, ONNX artifact, measured 2026-11-19)

Measured with `ml/scripts/evaluate_onnx.py`:
- The script uses the API's own preprocessing (letterbox, decoding, NMS) and the Ultralytics validation settings (conf 0.001, NMS IoU 0.7, up to 300 detections, 101-point AP).
- Full report: `ml/reports/eval_onnx_0.1.0-preview_val.json`.

| Class | Val instances | AP@0.50 | AP@0.50:0.95 | Precision | Recall |
|---|---|---|---|---|---|
| Plastic | 211 | 0.434 | 0.336 | 0.637 | 0.408 |
| Glass | 4 | 0.496 | 0.471 | 0.807 | 0.500 |
| Metal | 65 | 0.299 | 0.227 | 0.528 | 0.262 |
| Organic | 1 | 0.000 | 0.000 | – | 0.000 |
| Hazardous | 2 | 0.000 | 0.000 | – | 0.000 |
| **All (mean)** | 283 | **0.246** | **0.207** | 0.795 | 0.234 |

**Hazardous recall on validation is 0 out of 2.** The model cannot be relied on to flag batteries or aerosols, which is why the app always shows safety guidance and asks users to check items themselves. The Glass, Organic and Hazardous scores rest on only 1 to 4 instances, so they are not statistically meaningful.

### Pipeline check

To rule out an evaluator bug, the same script was run on the 841 **training** images. The model scored mAP@0.50 = 0.608 there: Plastic 0.832 and Metal 0.826. The evaluator scores a model highly on images it has learned. The gap to validation (0.43 and 0.30) shows the model overfits its small training set rather than generalising.

### Representative failures

From a held-out photo (`docs/screenshots/real-desktop-1440-results.png`):
- An almond-milk carton, which is out of scope, was detected as "Metal 50%".
- A clear plastic bottle was detected at only "Plastic 30%".
- Metal bottle caps and foil were found correctly (81%, 75%).
- The confusion matrix shows most misses are real objects predicted as background: 87 Plastic and 28 Metal missed.

### Speed and capacity

Measured on an Intel i7-8750H (Windows 11) with ONNX Runtime on CPU (2 threads), one API worker and a queue of 4:

| Load | Requests | OK | Rejected as busy (503) | Throughput | Client p50 | Client p95 | Model p50 / p95 |
|---|---|---|---|---|---|---|---|
| 1 client | 60 | 60 | 0 | 4.9 req/s | 204 ms | 247 ms | 195 / 241 ms |
| 4 clients | 60 | 60 | 0 | 5.0 req/s | 800 ms | 883 ms | 191 / 235 ms |
| 16 clients | 240 | 7 | 233 | 4.6 req/s | 882 ms | 1099 ms | 193 / 232 ms |

Server memory is about 320 MB. Overload is rejected immediately, and no request hung.

### Export parity

- **ONNX:** evaluated directly above, so the deployed artifact itself is measured.
- **TFLite:** checked on Android with `mobile/integration_test/model_test.dart`, by comparing its detections with ONNX on the same held-out photo (see mobile/README.md).
- **PyTorch:** a comparison against `best.pt` needs Colab, because PyTorch is blocked on the team laptop.

## Earlier runs (not usable, kept for the record)

`yolo_training_runs/` from `fyp.ipynb` trained on the Roboflow `taco-trashnet-current` export, which has **4 different classes**: `giay` (paper), `khac` (other), `kim_loai` (metal) and `nhua` (plastic). The app cannot use these checkpoints.

| Run | Model | Epochs done | Best val mAP@0.50 (their own split) |
|---|---|---|---|
| `ecorevive_yolov11_model_final` | YOLO11n | 25/25 | 0.786 |
| `ecorevive_yolov11_model_final-2` | YOLO11n | 11/25 | 0.676 |
| `ecorevive_yolov11_60epochs` | YOLO11s | 30/60 | 0.753 |

These scores are inflated and not comparable to ours:
- 1,444 of 4,346 source photos appear in more than one split, as augmented copies.
- Most images are single objects on plain backgrounds (TrashNet).
- Several labels contradict the photo's category.

## Next steps toward the target

1. **v2 dataset:** add the cleaned TrashNet portion of the Roboflow export (about 1,500 Glass boxes, plus extra Plastic and Metal), grouped by source photo, with all TACO copies removed so the locked test stays clean.
2. **Team photos:** collect about 200 Organic and 200 Hazardous labelled objects.
3. **Retrain, select and test:** retrain, select on validation, then run the locked test once with `evaluate_onnx.py --split test --confirm-locked-test`.
