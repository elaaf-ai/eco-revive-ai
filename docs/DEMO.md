# Evaluation demo and timeline

**Live site:** https://ecorevive-ai.vercel.app. Open it 2 minutes before you present, because the first visit after a quiet period takes a few extra seconds.

## Live demo (about 4 minutes)

1. **Home (20 s).** EcoRevive finds plastic waste and gives recycling and upcycling steps. Point out the model status line at the bottom: it says "preview", and say why.
2. **Scan (60 s).** Open **Scan** and start the camera, then hold up a plastic bottle and press the shutter. Boxes appear around the plastic, and other items are ignored.
3. **Guide (40 s).** Select the item. Show the upcycling steps, the precautions and the source label (AI-generated or curated).
4. **Item codes (40 s).** Type **001** in the search bar to show the water bottle's recycling steps and upcycling project. Open **All item codes** to show the 14 codes, then press **Another upcycling idea**.
5. **Safety (30 s).** Type "lithium battery" in the search. It gives **safe disposal steps**, never a craft idea. Then show an uncertain scan, where the app asks "Is this item plastic?" before giving a guide.
6. **Android (40 s).** Open the APK on a phone and scan the same bottle. Detection runs on the phone itself.

**Backup:** keep the screenshots in `docs/screenshots/` and a few test photos on the laptop, in case the venue has no network or camera.

## What each person explains

- **Model:** the dataset and its photo-batch splits, Kaggle GPU training, how v2 was chosen on validation, and why the locked test (68%) misses the 85% target. Real-use photos are the next step. See `EVALUATION.md`.
- **App:** the website and Android screens, camera handling, item codes and the plastic-only mode.
- **GenAI:** Gemini structured guides, the "different idea" variants, curated fallbacks and the hazardous safety rule.
- **Report and testing:** the QA bug report (27 fixes), the team test sheet, methodology and the architecture diagram.

## Timeline

| Phase | Planned | Status |
|---|---|---|
| Setup | GitHub, Drive, roles | Done. Collaborators still to be added |
| Data | TACO + TrashNet in Roboflow | Done (v1 and v2 datasets) |
| Training | YOLO11 on a GPU | Done (v2 on Kaggle T4) |
| Export | TFLite | Done, with an exact match to the original model |
| App | Flutter + website | Done: live website and APK built |
| GenAI | Gemini guides | Done, live |
| Integration | Camera in, guide out | Done, live |
| QA | Bug report and fixes | Done (27 of 27) |
| Testing | 4 × 10 real objects | **To do (team)** |
| Accuracy | 85% target | **Not met (68%)**. Needs team-collected photos and retraining |
| Rehearsal | Timed run-through | **To do (team)** |
