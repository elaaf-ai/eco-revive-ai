import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Runs only against a trained model: E2E_MODEL_DIR=models/current npx playwright test real-model
// Uses held-out validation photos (never committed) from the locally built dataset.
const here = path.dirname(fileURLToPath(import.meta.url));
const valDir = path.resolve(here, "../../ml/data/processed/taco-5class-v1/images/val");
const shots = path.resolve(here, "../../docs/screenshots");
const photos = ["batch_6_000017.jpg", "batch_4_000096.jpg"].map((name) => path.join(valDir, name));

test.use({ baseURL: "http://127.0.0.1:8011" });
test.skip(!process.env.E2E_MODEL_DIR, "Set E2E_MODEL_DIR to a trained model to run these checks");
test.skip(!photos.every((p) => fs.existsSync(p)), "Validation photos not available on this machine");

test("real model: upload, real boxes, guide", async ({ page }, info) => {
  await page.goto("/#/scan");
  await expect(page.getByText(/Model 0\.1\.0-preview/)).toBeVisible();

  const response = page.waitForResponse("**/v1/detect");
  await page.locator('input[type="file"]').setInputFiles(photos[0]!);
  const body = await (await response).json();
  expect(body.model.version).toBe("0.1.0-preview");

  if (body.detections.length === 0) {
    await expect(page.getByRole("heading", { name: "Nothing recognised" })).toBeVisible();
  } else {
    await expect(page.getByRole("heading", { name: /items? found/ })).toBeVisible();
    await expect(page.locator(".box")).toHaveCount(body.detections.length);
    await page.locator(".detection").first().click();
    await expect(page.locator("#guide-title, .confirm")).toBeVisible({ timeout: 30_000 });
  }
  await page.screenshot({ path: path.join(shots, `real-${info.project.name}-results.png`), fullPage: true });
});
