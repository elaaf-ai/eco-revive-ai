# Evaluation demo and timeline

## Live demo (target: 4 minutes)

1. **Home (20 s).** State what it does and the five classes. Point to the model status line at the bottom. It says "preview" until the locked test passes. Be upfront about it.
2. **Live camera (60 s).** Open Scan, start the camera, and hold up a plastic bottle. The live preview draws boxes about once a second.
3. **Capture and choose (40 s).** Capture a photo with a bottle and a can together. Two items are listed; select the can.
4. **Guide (40 s).** Show the steps and the sharp-edge precautions that are always added for metal, and read out the source label: AI-generated or curated.
5. **Safety (40 s).** Scan a battery. It gets the curated disposal guide, never a craft project. Then show an uncertain scan, where the app asks you to confirm the material before giving a guide.
6. **Android (40 s).** Repeat the capture on the phone app. Inference runs on the phone, so it works without internet.

**Backup plan:** keep screenshots of each step (`docs/screenshots/`) and a few test photos on the laptop, in case the venue has no network or camera.

## What each person explains

- **Person A (model):** how the dataset was built and split by collection batch, why YOLO11, how the test split is kept locked, and current results and gaps (DATASET.md, EVALUATION.md).
- **Person B (app):** web and Flutter screens, the camera handling, and how boxes are mapped back onto the photo.
- **Person C (GenAI):** why Gemini, the structured output with schema validation, the curated fallback, and the hazardous rule.
- **Person D (report and testing):** the test sheet results, the fixes made, the methodology chapter and the architecture diagram.

## Updated timeline

| Week | Planned (action plan) | Actual status |
|---|---|---|
| 0 | Setup, GitHub, Drive, roles | Drive done. GitHub repo exists locally, not yet pushed |
| 1–2 | Dataset | TACO 5-class dataset built and validated. Organic and Hazardous are too sparse |
| 3–5 | Train in Colab | Preview model trained and exported |
| 6 | TFLite export | Exported. Parity re-check pending |
| 3–7 | Flutter app | Built, tested, APK runs on the emulator. Needs the model file |
| 3–7 | Gemini guides | Built with fallback and safety rules. Needs an API key for live use |
| 7–9 | Integration and live demo | Web flow done end to end with the fixture model. Real model and hosting pending |
| next | Collect about 200 Organic and 200 Hazardous labeled objects, retrain, run the locked test once | Not started |
| 10–11 | Team test (4 × 10 objects), fixes, retest | Not started |
| 12 | Rehearsal, timing | Not started |
