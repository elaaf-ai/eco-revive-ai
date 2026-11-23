import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Scan history on the plastic server, which has a SQLite history database for each run.
// Every test gets a new browser context, so a new anonymous browser id and an empty history.
const here = path.dirname(fileURLToPath(import.meta.url));
const shots = path.resolve(here, "../../docs/screenshots");
const sample = path.resolve(here, "fixtures/sample-scene.jpg");

test.use({ baseURL: "http://127.0.0.1:8011" });
test.skip(Boolean(process.env.E2E_MODEL_DIR), "Fixture-model checks");

test("an uploaded scan is saved and shown in history", async ({ page }, info) => {
  await page.goto("/#/history");
  await expect(page.getByRole("heading", { name: "No saved scans yet" })).toBeVisible();

  await page.getByRole("link", { name: "Scan", exact: true }).click();
  const saved = page.waitForResponse((r) => r.url().includes("/v1/detect?save=true"));
  await page.locator('input[type="file"]').setInputFiles(sample);
  expect((await (await saved).json()).scan_id).toBeTruthy();
  await expect(page.getByRole("heading", { name: "1 item found" })).toBeVisible();

  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("heading", { name: "Your scan history" })).toBeVisible();
  await expect(page.getByText(/^1 plastic item, best \d+%$/)).toBeVisible();
  await expect(page.getByText("Scans saved")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: path.join(shots, `plastic-${info.project.name}-history.png`), fullPage: true });
});

test("live preview frames are not saved", async ({ page }) => {
  const saves: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("save=true")) saves.push(r.url());
  });
  const live = page.waitForResponse((r) => r.url().endsWith("/v1/detect"));
  await page.goto("/#/scan");
  await page.getByRole("button", { name: "Start camera" }).click();
  await live;
  expect(saves).toEqual([]);
  await page.goto("/#/history");
  await expect(page.getByRole("heading", { name: "No saved scans yet" })).toBeVisible();
});

test("history can be cleared after confirming", async ({ page }) => {
  await page.goto("/#/scan");
  const saved = page.waitForResponse((r) => r.url().includes("/v1/detect?save=true"));
  await page.locator('input[type="file"]').setInputFiles(sample);
  await saved;
  await page.goto("/#/history");
  await page.getByRole("button", { name: "Clear history" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No saved scans yet" })).toBeVisible();
});

test("the all-classes server has no history database, so there is no History link", async ({ page }) => {
  await page.goto("http://127.0.0.1:8010/");
  await expect(page.getByRole("link", { name: "Scan", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "History" })).toHaveCount(0);
});

test("feedback on a scanned item is counted for model learning", async ({ page }) => {
  await page.goto("/#/scan");
  await page.locator('input[type="file"]').setInputFiles(sample);
  await expect(page.getByRole("heading", { name: "1 item found" })).toBeVisible();
  const question = page.getByRole("group", { name: /Was Plastic 1 .*right\?/ });
  await expect(question).toBeVisible();
  const sent = page.waitForResponse((r) => r.url().endsWith("/v1/feedback"));
  await question.getByRole("button", { name: "Yes" }).click();
  expect((await sent).status()).toBe(200);
  await expect(page.getByText(/will help train the next model/)).toBeVisible();

  await page.goto("/#/history");
  await expect(page.getByRole("heading", { name: "Model learning" })).toBeVisible();
  await expect(page.getByText("Answers collected")).toBeVisible();
});
