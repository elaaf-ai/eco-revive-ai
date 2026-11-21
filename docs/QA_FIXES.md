# QA bug report fixes (report of 2026-11-20 by Ahmer)

All 27 items are addressed. Each fix has a regression test unless noted.

- **Backend tests:** `backend/tests/test_qa_regressions.py`
- **Web tests:** `web/src/qaRegressions.test.tsx`, `web/src/useCamera.test.ts`, `web/e2e/plastic.spec.ts`
- **Mobile tests:** `mobile/test/qa_regressions_test.dart`
- **ML tests:** `ml/tests/test_qa_regressions.py`, `ml/tests/test_ci_gate.py`

| ID | Fix | Test |
|---|---|---|
| B-01 | Item names such as battery, lithium, aerosol, spray can, vape, paint tin and chemicals always return the curated **disposal** guide, whatever class the request names | `test_b01_*` |
| B-02 | The unsafe-content filter matches word stems (burn\*, melt\*, solder\*, grind\*, smash\*, punctur\*, acid\*, heat guns, shatter\*, flame\*, ignit\*) | `test_b02_*` |
| B-03 | Any model-load error, including a manifest missing keys, gives 503 with the reason. Startup never crashes | `test_b03_*` |
| B-04 | Failed loads are retried with backoff (5 s doubling to 5 min) | `test_b04_*` |
| B-05 | The skip link focuses `#main` without navigating. Only `#/…` hashes change the screen | `B-05` (vitest) |
| B-06 | `TimeoutError` aborts count as a slow connection. This turns on retry, the message and the live-preview slowdown | `B-06` (vitest) |
| B-07 | The idempotency store evicts the oldest completed entries instead of refusing. Each client is limited to 200 entries, and only too many *in-flight* requests are refused (429) | `test_b07_*` |
| B-08 | Docker trusts forwarded headers only from `FORWARDED_ALLOW_IPS` (default 127.0.0.1). The app reads a client-IP header only when `ECOREVIVE_CLIENT_IP_HEADER` is set; it is set to `x-forwarded-for` on Vercel, which overwrites that header | `test_b08_*` |
| B-09 | The release gate reads every page of check runs and requires the named jobs ml, backend, web, e2e, mobile and docker to have concluded `success`. Its own running check never counts | `test_ci_gate.py` |
| B-10 | The request ID is set before handling. Unhandled 500s keep the request ID and security headers. Null bytes and invalid paths return 404 | `test_b10_*` |
| B-11 | "Another idea" sends `variant` 1–9, which is part of the cache key and the prompt. The button stays visible and is hidden when Gemini is off | `test_b11_*`, `B-11` (vitest) |
| B-12 | Gemini reports `matches_category`, and items that are not plastic get 422 `not_this_material`. Symbol-only hints are refused. Codes are looked up on the server when the local list is missing, so network errors are shown | `test_b12_*`, `B-12` (vitest) |
| B-13 | CSP `font-src 'self' data:` | `test_b13_*` |
| B-14 | The upload media type is compared in lower case | `test_b14_*` |
| B-15 | The mobile guide service never throws: bad replies and TLS errors fall back to a labelled curated guide, and the guide view handles errors | `B-15` (flutter) |
| B-16 | Mobile capture catches every error and shows a snackbar | Code fix. The emulator path is not automated |
| B-17 | Mobile `_start()` has an in-progress guard, so the camera cannot start twice | Code fix. Still needs a device test |
| B-18 | Mobile 4xx replies show the server's message. The mobile app reads `shared/product.json` (Plastic only), as the backend does | `B-18` (flutter) |
| B-19 | A blank `q` lists all items | `test_b19_*` |
| B-20 | The web app re-checks readiness with backoff until the model is ready | `B-20` (vitest) |
| B-21 | The camera resumes when the tab becomes visible again, if it was on before | `useCamera.test.ts` |
| B-22 | A failed live scan clears the previous boxes | `B-22` (Playwright) |
| B-23 | A replayed response carries its original request ID in both the body and the `X-Request-ID` header | `test_b23_*` |
| B-24 | `/v1/metrics` is hidden (404) unless `ECOREVIVE_METRICS_TOKEN` is set and sent as a Bearer token | `test_b24_*` |
| B-25 | Unknown file paths (with an extension) return 404. App routes still return the page | `test_b10_b25_*` |
| B-26 | `validate_dataset.py` accepts `names` as a list or dict. `evaluate_onnx.py` exits with a clear message on an empty split | `test_b26_*` |
| B-27 | Export parity now checks both directions: extra detections in the export fail the check. In `prepare_taco.py`, photos whose only objects are out of scope are **kept as negatives by design**, so the detector learns that cartons and paper are not plastic. This is now an explicit, recorded option (`--out-of-scope-only keep\|drop`) | `test_b27_*` |

## Verified locally

| Check | Result |
|---|---|
| Backend tests | 88 passed |
| Backend lint and type checks | Clean |
| Web unit tests | 31 passed |
| Web lint and type checks | Clean |
| Browser checks (390, 768, 1440 px) | 45 passed |
| ML tests | 24 passed |
| Flutter analysis | Clean |
| Flutter tests | 15 passed |

## Not verified

- **B-16 and B-17 on a real phone.** The fixes are in code, and the lifecycle double-start (B-17) still needs a device test.
- **Flutter tests on this laptop.** Smart App Control blocks Flutter's shader compiler, so the tests were run with `--no-test-assets`. CI runs them normally on Linux.
