# Evaluation

Target: **mAP@0.50 ≥ 0.85 on the locked held-out test split.** Only results measured on that split count toward the target.

## Current status (2026-11-19)

| Item | Status | Evidence |
|---|---|---|
| `0.1.0-preview` trained and exported | Done in Colab | Export manifest checksums in `models/registry/0.1.0-preview.json` |
| Which baseline won on validation | **Not yet reported** | Output of the notebook's "Choose the candidate" cell is needed |
| Validation metrics | **Not yet reported** | `My Drive/FYP/ecorevive/reports/` |
| Export parity, first run | **Inconclusive** | 89% match. The check fed `best.pt` and the exports different padding, which is a flaw in the check, now fixed |
| Export parity, corrected run | Pending | Corrected cell given to the team; needs PyTorch, so it runs in Colab |
| Locked test mAP@0.50 / 0.50:0.95 / per-class AP / P / R / confusion matrix | **Not measured** | Do not quote a number until `evaluate.py --split test` has run on the final artifact |
| Inference latency of the real model | Not measured | Needs the ONNX file on this machine |

**Expected outcome:** the target will probably be missed while Organic and Hazardous have almost no data (see DATASET.md). Hazardous recall cannot be measured with one test instance.

## Historical runs from `fyp.ipynb` (not comparable)

These were trained on the 4-class Roboflow dataset, stopped early, and evaluated on its validation split only. They are not test results and do not cover the 5-class task.

| Run | Stopped at | Best validation mAP@0.50 | mAP@0.50:0.95 |
|---|---|---|---|
| YOLO11n (`ecorevive_yolov11_model_final-2`) | epoch 12/25 | 0.676 (epoch 11) | 0.569 |
| YOLO11s (`ecorevive_yolov11_60epochs`) | epoch 10/60 | 0.581 (epoch 9) | 0.485 |

## Serving performance (measured locally)

- **Host:** Intel i7-8750H, 12 logical CPUs, Windows 11. One API worker with a queue of 4, ONNX Runtime CPU, 2 threads.
- **Model:** the **fixture model** (fixed output). These numbers measure API overhead only (decode, letterbox, NMS, JSON), not real YOLO compute.

| Load | Requests | 200 | 503 overloaded | Throughput | p50 | p95 |
|---|---|---|---|---|---|---|
| 4 concurrent clients | 200 | 200 | 0 | 21.3 req/s | 154 ms | 368 ms |
| 16 concurrent clients | 400 | 25 | 375 | 24.8 req/s | 216 ms | 339 ms |

Overload was rejected immediately with `Retry-After`. No request hung or errored. **Re-run with the real model before choosing worker count or host size:** `python backend/scripts/load_test.py --image <photo> --concurrency 4`.

## How to finish this report

1. Run the corrected parity cell in Colab. Paste the `PARITY` and `VAL` lines here.
2. Once the candidate is final, run the locked test cell **once**. Copy the test JSON files into `ml/reports/` and fill in the table below.
3. Update `models/registry/<version>.json`: `evaluation.status`, `locked_test_map50`, `meets_target`.

| Class | Test instances | AP@0.50 | AP@0.50:0.95 | Precision | Recall |
|---|---|---|---|---|---|
| Plastic | 217 | – | – | – | – |
| Glass | 81 | – | – | – | – |
| Metal | 71 | – | – | – | – |
| Organic | 1 | – | – | – | – |
| Hazardous | 1 | – | – | – | – |
