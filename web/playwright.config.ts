import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// UI review and end-to-end checks against the real backend serving the built site.
// Two servers start: port 8010 with all five classes enabled (flow.spec.ts) and port 8011 in the
// plastic-only product mode with scan history (plastic.spec.ts, history.spec.ts, real-model.spec.ts). By default they load the fixture
// model (fixed boxes, labelled as not a real model). Set E2E_MODEL_DIR to use a trained model.
export const ALL_CLASSES_PORT = 8010;
export const PLASTIC_PORT = 8011;
const modelDir = process.env.E2E_MODEL_DIR ?? "models/fixture";
// The plastic server keeps scan history in a fresh SQLite file for each run.
const historyDb = path.join(os.tmpdir(), `ecorevive-e2e-${Date.now()}.db`);
const python = process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";

const server = (port: number, enabledClasses: string[], extraEnv: Record<string, string> = {}) => ({
  command: `${python} -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port ${port}`,
  cwd: "../backend",
  url: `http://127.0.0.1:${port}/readyz`,
  reuseExistingServer: false,
  timeout: 60_000,
  env: {
    ECOREVIVE_MODEL_DIR: modelDir,
    ECOREVIVE_STATIC_DIR: "../web/dist",
    ECOREVIVE_DETECT_PER_MINUTE: "1000",
    ECOREVIVE_LOG_LEVEL: "WARNING",
    ECOREVIVE_ENABLED_CLASSES: JSON.stringify(enabledClasses),
    GEMINI_API_KEY: "",
    ...extraEnv,
  },
});

export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/.results",
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${ALL_CLASSES_PORT}`,
    channel: "chrome",
    launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
    permissions: ["camera"],
    reducedMotion: "reduce",
  },
  projects: [
    { name: "phone-390", use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
    { name: "tablet-768", use: { viewport: { width: 768, height: 1024 } } },
    { name: "desktop-1440", use: { viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    server(ALL_CLASSES_PORT, ["Plastic", "Glass", "Metal", "Organic", "Hazardous"]),
    server(PLASTIC_PORT, ["Plastic"], { ECOREVIVE_DATABASE_URL: `sqlite:///${historyDb}` }),
  ],
});
