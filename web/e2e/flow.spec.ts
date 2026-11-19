import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

// These checks rely on the fixture model's fixed boxes; real-model.spec.ts covers trained models.
test.skip(Boolean(process.env.E2E_MODEL_DIR), "Fixture-model checks");

const here = path.dirname(fileURLToPath(import.meta.url));
const shots = path.resolve(here, "../../docs/screenshots");
const sample = path.resolve(here, "fixtures/sample-scene.jpg");

async function shot(page: Page, name: string, projectName: string) {
  await page.screenshot({ path: path.join(shots, `${projectName}-${name}.png`), fullPage: true });
}

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("home screen", async ({ page }, info) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText("fixture-not-a-real-model", { exact: false })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await shot(page, "home", info.project.name);
});

test("upload to boxes to guide", async ({ page }, info) => {
  await page.goto("/#/scan");
  await page.locator('input[type="file"]').setInputFiles(sample);
  await expect(page.getByRole("heading", { name: "2 items found" })).toBeVisible();

  // Boxes must line up with the image: the fixture's Plastic box spans x 25%-75% of the frame.
  const frame = await page.locator(".stage-frame").boundingBox();
  const box = await page.locator(".box").first().boundingBox();
  expect(frame && box).toBeTruthy();
  if (frame && box) {
    const expectedLeft = frame.x + frame.width * 0.34375;
    expect(Math.abs(box.x - expectedLeft)).toBeLessThan(3);
  }
  await expectNoHorizontalScroll(page);
  await shot(page, "results", info.project.name);

  await page.getByRole("button", { name: /^Plastic/ }).click();
  await expect(page.locator("#guide-title")).toBeVisible();
  await expect(page.getByText("Curated guide ·", { exact: false })).toBeVisible();
  await shot(page, "guide", info.project.name);

  await page.getByRole("button", { name: /^Hazardous/ }).click();
  await expect(page.getByText("Safe disposal")).toBeVisible();
  await shot(page, "hazardous", info.project.name);
});

test("live camera preview", async ({ page }, info) => {
  await page.goto("/#/scan");
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.locator("video")).toBeVisible();
  await expect(page.locator(".box").first()).toBeVisible({ timeout: 10_000 });
  await shot(page, "camera-live", info.project.name);

  // Leaving the scanner must stop every camera track. Keep a handle on the stream first,
  // because the video element disappears with the scanner.
  const trackCount = await page.evaluate(() => {
    const stream = document.querySelector("video")?.srcObject as MediaStream | null;
    (window as unknown as { __cameraStream?: MediaStream }).__cameraStream = stream ?? undefined;
    return stream?.getTracks().length ?? 0;
  });
  expect(trackCount).toBeGreaterThan(0);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Home" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as unknown as { __cameraStream: MediaStream }).__cameraStream
          .getTracks()
          .every((t) => t.readyState === "ended"),
      ),
    )
    .toBe(true);
});

test("camera that finishes opening after leaving is closed", async ({ page }) => {
  await page.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await original(constraints);
      (window as unknown as { __lateStream?: MediaStream }).__lateStream = stream;
      await new Promise((resolve) => setTimeout(resolve, 800));
      return stream;
    };
  });
  await page.goto("/#/scan");
  await page.getByRole("button", { name: "Start camera" }).click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Home" }).click();
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const stream = (window as unknown as { __lateStream?: MediaStream }).__lateStream;
          return stream ? stream.getTracks().every((t) => t.readyState === "ended") : null;
        }),
      { timeout: 5000 },
    )
    .toBe(true);
});

test("camera permission denied", async ({ page }, info) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("denied", "NotAllowedError"));
  });
  await page.goto("/#/scan");
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.getByRole("main").getByText("Camera access was blocked", { exact: false })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Camera access was blocked" })).toBeAttached();
  await expect(page.getByRole("button", { name: "Upload a photo" })).toBeEnabled();
  await shot(page, "camera-denied", info.project.name);
});

test("empty scan", async ({ page }, info) => {
  await page.route("**/v1/detect", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.detections = [];
    body.quality = { status: "no_detections", message: "No waste item recognised. Fill the frame with one item on a plain background.", image_hints: ["too_dark"] };
    await route.fulfill({ response, json: body });
  });
  await page.goto("/#/scan");
  await page.locator('input[type="file"]').setInputFiles(sample);
  await expect(page.getByRole("heading", { name: "Nothing recognised" })).toBeVisible();
  await shot(page, "empty", info.project.name);
});

test("uncertain scan asks for confirmation", async ({ page }, info) => {
  await page.route("**/v1/detect", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.detections = body.detections.slice(0, 1).map((d: { confidence: number }) => ({ ...d, confidence: 0.34 }));
    body.quality = { status: "low_confidence", message: "The scan is not sure. Retake the photo closer, in good light, or confirm the material.", image_hints: [] };
    await route.fulfill({ response, json: body });
  });
  await page.goto("/#/scan");
  await page.locator('input[type="file"]').setInputFiles(sample);
  await expect(page.getByRole("group", { name: "What is this item made of?" })).toBeVisible();
  await shot(page, "confirm", info.project.name);
  await page.getByRole("radio", { name: "Glass" }).check();
  await page.getByRole("button", { name: "Show guide for Glass" }).click();
  await expect(page.getByText("chipped", { exact: false })).toBeVisible();
});

test("server busy", async ({ page }, info) => {
  await page.route("**/v1/detect", (route) =>
    route.fulfill({
      status: 503,
      headers: { "Retry-After": "1" },
      json: { error: { code: "overloaded", message: "The scanner is busy. Try again in a moment.", request_id: "x", retry_after_s: 0.2 } },
    }),
  );
  await page.goto("/#/scan");
  await page.locator('input[type="file"]').setInputFiles(sample);
  await expect(page.getByRole("main").getByText("The scanner is busy", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await shot(page, "busy", info.project.name);
});

test("keyboard can reach the scanner controls", async ({ page }) => {
  await page.goto("/#/scan");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("Tab");
    const name = await page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.textContent);
    if (name?.includes("Start camera")) return;
  }
  throw new Error("Start camera button was not reachable by keyboard");
});
