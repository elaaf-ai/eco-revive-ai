import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

// The product mode: only Plastic is detected and shown, plus a search bar for guides.
const here = path.dirname(fileURLToPath(import.meta.url));
const shots = path.resolve(here, "../../docs/screenshots");
const sample = path.resolve(here, "fixtures/sample-scene.jpg");

test.use({ baseURL: "http://127.0.0.1:8011" });
test.skip(Boolean(process.env.E2E_MODEL_DIR), "Fixture-model checks");

test("home shows the plastic product and a search bar", async ({ page }, info) => {
  await page.goto("/");
  await expect(page.getByText("Plastic scanner")).toBeVisible();
  await expect(page.getByText(/spots plastic waste/)).toBeVisible();
  await expect(page.getByText("Hazardous")).toHaveCount(0);
  await expect(page.getByRole("search")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: path.join(shots, `plastic-${info.project.name}-home.png`), fullPage: true });
});

test("item code 001 shows the water bottle's recycling and upcycling methods", async ({ page }, info) => {
  await page.goto("/");
  await page.getByRole("searchbox", { name: "Item code or name" }).fill("001");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Water bottle" })).toBeVisible();
  await expect(page.getByLabel("Item code 001")).toBeVisible();
  await expect(page.getByRole("heading", { name: /Recycling/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Upcycling: Self-watering planter/ })).toBeVisible();
  await expect(page.getByText("All item codes (14)")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: path.join(shots, `plastic-${info.project.name}-search.png`), fullPage: true });
});

test("typing a name suggests coded items", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("searchbox", { name: "Item code or name" }).fill("yog");
  await page.getByRole("list", { name: "Matching items" }).getByRole("button", { name: /005\s*Yogurt cup/ }).click();
  await expect(page.getByRole("heading", { name: "Yogurt cup" })).toBeVisible();
});

test("scan shows only plastic boxes", async ({ page }, info) => {
  await page.goto("/#/scan");
  await page.locator('input[type="file"]').setInputFiles(sample);
  await expect(page.getByRole("heading", { name: "1 item found" })).toBeVisible();
  await expect(page.locator(".box")).toHaveCount(1);
  await expect(page.getByRole("button", { name: /^Plastic/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Hazardous/ })).toHaveCount(0);
  await expect(page.locator("#guide-title")).toBeVisible();
  await page.screenshot({ path: path.join(shots, `plastic-${info.project.name}-results.png`), fullPage: true });
});

test("uncertain plastic scan asks yes or no", async ({ page }) => {
  await page.route("**/v1/detect*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.detections = body.detections.map((d: { confidence: number }) => ({ ...d, confidence: 0.33 }));
    body.quality = { status: "low_confidence", message: "The scan is not sure.", image_hints: [] };
    await route.fulfill({ response, json: body });
  });
  await page.goto("/#/scan");
  await page.locator('input[type="file"]').setInputFiles(sample);
  await expect(page.getByRole("group", { name: "Is this item plastic?" })).toBeVisible();
  await page.getByRole("button", { name: "Yes, it's plastic" }).click();
  await expect(page.locator("#guide-title")).toBeVisible();
});

test("B-22: a failed live scan clears the previous boxes", async ({ page }) => {
  let calls = 0;
  await page.route("**/v1/detect*", async (route) => {
    calls += 1;
    if (calls === 1) return route.fallback();
    return route.fulfill({
      status: 503,
      headers: { "Retry-After": "1" },
      json: { error: { code: "overloaded", message: "Busy", request_id: "x", retry_after_s: 1 } },
    });
  });
  await page.goto("/#/scan");
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.locator(".box").first()).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".box")).toHaveCount(0, { timeout: 10_000 });
});
