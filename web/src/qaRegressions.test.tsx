// Regression tests for the QA bug report of 2026-11-20 (web items).
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { ApiError, detect } from "./api";
import { App } from "./App";
import { GuideSearch } from "./components/GuideSearch";
import { ItemCard } from "./components/ItemCard";
import type { CatalogItem } from "./types";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.location.hash = "";
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const item: CatalogItem = {
  code: "001",
  name: "Water bottle",
  aliases: [],
  resin: { number: 1, type: "PET" },
  recycling: { accepted: "Yes.", steps: ["One.", "Two.", "Three."] },
  upcycling: { title: "Planter", materials: ["Bottle"], steps: ["One.", "Two.", "Three."], precautions: [] },
  safety_notice: "A photo cannot confirm what an item contains.",
  catalog_version: "1.0.0",
};

const guideBody = (title: string) => ({
  api_version: "1",
  request_id: "g",
  cached: false,
  guide: {
    class_name: "Plastic",
    kind: "upcycle",
    title,
    materials: ["Bottle"],
    steps: ["One.", "Two.", "Three."],
    precautions: [],
    source: "gemini",
    source_detail: "Generated",
    safety_notice: "A photo cannot confirm what an item contains.",
  },
});

it("B-06: our own request timeout is reported as a slow connection", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    (_url, init) =>
      new Promise((_, reject) =>
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason ?? new DOMException("x", "AbortError"))),
      ),
  );
  const error = await detect(new Blob(["x"]), { timeoutMs: 10 }).catch((e) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 0, code: "timeout" });
});

it("B-12: symbol-only input sends nothing", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ version: "1", items: [] }));
  render(<GuideSearch material="Plastic" announce={() => {}} />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Item code or name" }), "#");
  await userEvent.click(screen.getByRole("button", { name: "Search" }));
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/v1/guides"))).toHaveLength(0);
});

it("B-12: if the item list failed to load, a code is looked up on the server and errors are real", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/v1/items")) throw new TypeError("Failed to fetch");
    if (url.endsWith("/v1/items/001")) return json(item);
    throw new TypeError("Failed to fetch");
  });
  render(<GuideSearch material="Plastic" announce={() => {}} />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Item code or name" }), "1");
  await userEvent.click(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByRole("heading", { name: "Water bottle" })).toBeInTheDocument();

  await userEvent.clear(screen.getByRole("searchbox", { name: "Item code or name" }));
  await userEvent.type(screen.getByRole("searchbox", { name: "Item code or name" }), "002");
  await userEvent.click(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByText(/Can't reach EcoRevive/)).toBeInTheDocument();
});

it("B-11: 'Another idea' asks for a new variant each time and is hidden without Gemini", async () => {
  const titles = ["Idea one", "Idea two"];
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => json(guideBody(titles.shift() ?? "Idea three")));
  const { rerender } = render(<ItemCard item={item} material="Plastic" announce={() => {}} aiAvailable />);
  await userEvent.click(screen.getByRole("button", { name: /Another upcycling idea/ }));
  expect(await screen.findByRole("heading", { name: "Idea one" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Show a different idea/ }));
  expect(await screen.findByRole("heading", { name: "Idea two" })).toBeInTheDocument();
  const variants = fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init!.body)).variant);
  expect(variants).toEqual([1, 2]);

  rerender(<ItemCard item={item} material="Plastic" announce={() => {}} aiAvailable={false} />);
  expect(screen.queryByRole("button", { name: /different idea|Another upcycling idea/ })).not.toBeInTheDocument();
});

it("B-05: the skip link focuses the page without leaving the scan screen", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    json({ ready: true, model_loaded: true, model: null, guide_provider: "curated_only", detail: "ready" }),
  );
  window.location.hash = "#/scan";
  render(<App />);
  await userEvent.click(screen.getByRole("link", { name: "Skip to content" }));
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(document.activeElement?.id).toBe("main");
  expect(screen.getByRole("region", { name: "Scanner" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Scan" })).toHaveAttribute("aria-current", "page");
});

it("B-20: readiness is checked again until the model is ready", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const states = [
    { ready: false, model_loaded: false, model: null, guide_provider: "curated_only", detail: "Model is loading." },
    {
      ready: true,
      model_loaded: true,
      model: { version: "9.9.9-preview", status: "preview", format: "onnx", classes: ["Plastic"], enabled_classes: ["Plastic"] },
      guide_provider: "gemini",
      detail: "ready",
    },
  ];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
    String(input).endsWith("/readyz") ? json(states.length > 1 ? states.shift() : states[0]) : json({ items: [] }),
  );
  render(<App />);
  expect(await screen.findByText("Model offline")).toBeInTheDocument();
  await act(async () => {
    vi.advanceTimersByTime(5000);
  });
  await waitFor(() => expect(screen.getByText(/Model 9\.9\.9-preview/)).toBeInTheDocument());
});
