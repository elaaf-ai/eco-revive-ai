# Dataset provenance: `taco-5class-v1`

## Sources

| Source | What we used | Licence | Status |
|---|---|---|---|
| TACO (`pedropro/TACO`, commit `70479ad9adc3da971a8ae75ac97eb1026910eec7`) | 1,500 images, 4,784 box annotations, 60 categories | Annotations CC BY 4.0. Images carry per-image terms: 224 marked "CC", 380 "ODbL (c) OpenLitterMap & Contributors", 619 with no licence field | Used |
| TrashNet | Not used | MIT | Image-level labels only. Its images need reviewed boxes before they can train a detector |
| Roboflow `taco-trashnet-current.v1i.yolov11` (from `fyp.ipynb`) | Not used | Unknown: depends on the Roboflow project | 4 classes; held in the team's Drive only |
| Team photos | Not yet collected | Team-owned | Needed for Organic and Hazardous |

**Before public release:** confirm the terms for the 619 TACO images that have no licence field. Keep the ODbL attribution for the OpenLitterMap images. The per-image licence is recorded in `ml/manifests/taco-5class-v1.manifest.jsonl`.

## Label mapping (`ml/configs/taco_mapping_v1.yaml`)

- **Plastic:** bottles, caps, cups, lids, film, wrappers, bags, containers, utensils, straws, styrofoam.
- **Glass:** glass bottles, jars and cups, and broken glass. Broken glass is a handling risk, not a chemical hazard, so the guide layer adds sharp-edge rules.
- **Metal:** cans, foil, metal caps and lids, pop tabs, scrap metal.
- **Organic:** food waste.
- **Hazardous:** batteries and aerosol cans, meaning items that need special collection because of their contents.
- **Out of scope (left unlabeled):** paper, cardboard and cartons, cigarettes, rope, shoes. The detector learns to ignore them.
- **Ambiguous (whole image excluded, 277 images):** "Unlabeled litter", blister packs, plastified paper bags, squeezable tubes. Leaving them unlabeled would teach the model that real waste is background.

## Splits

- Splits are made by TACO collection batch (15 batches), so photos from the same session stay together.
- The batch assignment was searched with seed 42 to keep each class's share in each split close to 70/15/15.
- Exact duplicates are checked by SHA-256. Near-duplicates are checked by perceptual hash with Hamming distance ≤ 4: 2 pairs were found, both within one split.
- The test split (batches 3, 8, 10) is locked. Model selection uses validation (batches 4, 6) only.

| Split | Images | Background | Plastic | Glass | Metal | Organic | Hazardous |
|---|---|---|---|---|---|---|---|
| train | 841 | 75 | 1104 | 83 | 283 | 3 | 6 |
| val | 172 | 18 | 211 | 4 | 65 | 1 | 2 |
| test | 210 | 26 | 217 | 81 | 71 | 1 | 1 |

## Known gaps

- **Organic and Hazardous are effectively missing:** 5 Organic and 9 Hazardous objects in total. The model cannot learn them from this data, and one test instance per class cannot measure them. This is the main blocker for the 0.85 target and for safe Hazardous recall.
- Validation has only 4 Glass instances, so validation scores for Glass are noisy.
- TACO shows litter outdoors. Indoor, hand-held photos like the demo will look different.

**Collection plan:** at least 200 labeled objects per weak class, photographed by the team in demo-like conditions with several items per photo, and labelled with boxes in Roboflow or CVAT. Add them as new batches, so splits stay grouped by session. Bump the dataset version to `-v2`.
