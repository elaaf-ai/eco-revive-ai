# Team test plan (Phase 8 of the action plan)

Each of the four team members tests **10 different real objects**. Use a mix that covers every class: bottles, cans, jars, food scraps, and at least one battery and one aerosol can (handle these with care and don't open them). Include a few multi-item photos, one empty scene, and one item that is out of scope, such as paper.

Record results in `docs/team_test_sheet.csv`, one row per scan. **Only record scans that really happened.** Leave the result columns empty until you run the test.

| Column | What to write |
|---|---|
| tester | Your name |
| date | YYYY-MM-DD |
| platform | `web-phone`, `web-desktop` or `android` |
| model_version | Shown at the bottom of the site or on the app home screen |
| object | What it actually is, for example "500 ml water bottle" |
| expected_class | Plastic, Glass, Metal, Organic, Hazardous, or `none` |
| predicted_class | Top detection, or `none` |
| confidence | As shown, for example 0.82 |
| guide_source | `gemini`, `curated` or `offline` |
| pass | `yes` if predicted = expected and the guide makes sense |
| failure_notes | Be specific: "app showed no box when bottle was on a white table", not "broken" |
| owner | Who fixes it: A (model), B (app), C (guides) |
| retest_date / retest_pass | After the fix |
