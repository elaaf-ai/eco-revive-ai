# Model card: EcoRevive detector `0.1.0-preview`

- **Task:** object detection of waste in photos. Classes: Plastic, Glass, Metal, Organic, Hazardous.
- **Architecture:** Ultralytics YOLO11, fine-tuned from COCO-pretrained weights at 640 px. The selected checkpoint is 19 MB, which matches YOLO11s; confirm with the notebook's candidate output.
- **Training data:** `taco-5class-v1` (TACO, see DATASET.md). Seed 42. Trained in Google Colab with `ultralytics==8.4.212`.
- **Formats:**
  - `best.pt`: source checkpoint.
  - `model.onnx`: web API, ONNX Runtime CPU.
  - `model.tflite`: Android, float32.
  - Checksums are in `models/registry/0.1.0-preview.json`.
- **Input/output:** RGB, letterboxed to 640×640 with grey (114) padding, values 0–1. Output `[1, 9, 8400]`: box centre x, y, width, height, then 5 class scores. The TFLite boxes are normalised to 0–1. Non-maximum suppression runs in the app and the API, not in the model.

## Intended use

A learning tool that suggests a material category and a reuse or disposal idea, with a person checking the item.

## Not for

Deciding whether an item is safe to touch, sorting hazardous waste without a person checking it, or any compliance decision.

## Performance

**Not yet evaluated on the locked test split.** See EVALUATION.md. Do not describe this model as meeting the 0.85 target.

## Known limitations

- Organic (5 objects) and Hazardous (9 objects) are barely represented, so expect missed and wrong predictions for food waste, batteries and aerosols.
- TACO is mostly outdoor litter, so hand-held indoor photos may score lower.
- Broken glass is labelled Glass. Sharp-edge safety comes from the guide rules, not from the model.
- Paper and cardboard are deliberately out of scope, so the model should not detect them.

## Safety controls around the model

- Hazardous results always get the curated disposal guide. Generated text is never used for them.
- Uncertain scans (top confidence below 0.5, or two overlapping boxes with different classes and close confidence) require a retake or user confirmation before a guide is shown.
- Every guide states that a photo cannot confirm an item is safe to handle.
