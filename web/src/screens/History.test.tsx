import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { detect } from "../api";
import type { HistoryResponse } from "../types";
import { History } from "./History";

afterEach(() => vi.restoreAllMocks());

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const withScans: HistoryResponse = {
  api_version: "1",
  scans: [
    {
      id: "a1",
      created_at: "2026-11-23T09:15:00.000Z",
      model_version: "0.2.0-preview-small",
      quality: "ok",
      item_count: 2,
      top_class: "Plastic",
      top_confidence: 0.82,
      inference_ms: 140,
      items: [
        { class_name: "Plastic", confidence: 0.82 },
        { class_name: "Plastic", confidence: 0.4 },
      ],
    },
    {
      id: "a0",
      created_at: "2026-11-22T18:00:00.000Z",
      model_version: "0.2.0-preview-small",
      quality: "no_detections",
      item_count: 0,
      top_class: null,
      top_confidence: null,
      inference_ms: 130,
      items: [],
    },
  ],
  you: { scans: 2, items_found: 2, items_this_week: 2 },
  everyone: { scans: 40, items_found: 57 },
};

const learning = {
  api_version: "1",
  enabled: true,
  feedback: 12,
  correct: 9,
  wrong: 3,
  training_photos: 5,
  model_version: "0.2.0-preview-small",
  next_step: "5 of 50 shared photos collected before the next training round.",
};

/** Answers /v1/learning separately; everything else gets the given history response. */
function mockHistory(body: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
    String(input).includes("/v1/learning") ? json(learning) : json(body, status),
  );
}

const empty: HistoryResponse = { ...withScans, scans: [], you: { scans: 0, items_found: 0, items_this_week: 0 } };

it("shows totals and recent scans", async () => {
  mockHistory(withScans);
  render(<History announce={() => {}} enabled />);
  expect(await screen.findByText("2 plastic items, best 82%")).toBeInTheDocument();
  expect(screen.getByText("No plastic found")).toBeInTheDocument();
  expect(screen.getByText("57")).toBeInTheDocument();
  expect(screen.getByText("Found by everyone using EcoRevive")).toBeInTheDocument();
});

it("sends the browser id and shows an empty state", async () => {
  const fetchMock = mockHistory(empty);
  render(<History announce={() => {}} enabled />);
  expect(await screen.findByText("No saved scans yet")).toBeInTheDocument();
  const [url, init] = fetchMock.mock.calls.find(([u]) => String(u).includes("/v1/history"))!;
  expect(String(url)).toContain("/v1/history?limit=20");
  expect(new Headers(init?.headers).get("X-Client-Id")).toBeTruthy();
});

it("asks before clearing, then deletes and reloads", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    if (String(_input).includes("/v1/learning")) return json(learning);
    if (init?.method === "DELETE") return json({ deleted: 2 });
    return json(fetchMock.mock.calls.some(([, i]) => i?.method === "DELETE") ? empty : withScans);
  });
  const announce = vi.fn();
  render(<History announce={announce} enabled />);
  await userEvent.click(await screen.findByRole("button", { name: "Clear history" }));
  expect(screen.getByText("Delete all 2 saved scans from this browser?")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(announce).toHaveBeenCalledWith("Deleted 2 saved scans."));
  expect(await screen.findByText("No saved scans yet")).toBeInTheDocument();
});

it("shows the server's message when history is unavailable", async () => {
  mockHistory({ error: { code: "history_unavailable", message: "Scan history is unavailable. Try again shortly." } }, 503);
  render(<History announce={() => {}} enabled />);
  expect(await screen.findByText("Scan history is unavailable. Try again shortly.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
});

it("explains when the server has no history database", () => {
  const fetchMock = vi.spyOn(globalThis, "fetch");
  render(<History announce={() => {}} enabled={false} />);
  expect(screen.getByText(/not set up on this server/)).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("asks the server to save only when requested", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({ detections: [] }));
  await detect(new Blob(["x"], { type: "image/jpeg" }), {});
  await detect(new Blob(["x"], { type: "image/jpeg" }), { save: true });
  expect(String(fetchMock.mock.calls[0]![0])).toMatch(/\/v1\/detect$/);
  expect(String(fetchMock.mock.calls[1]![0])).toMatch(/\/v1\/detect\?save=true$/);
});

it("shows how the model learns from feedback", async () => {
  mockHistory(withScans);
  render(<History announce={() => {}} enabled />);
  expect(await screen.findByRole("heading", { name: "Model learning" })).toBeInTheDocument();
  expect(screen.getByText("9 / 3")).toBeInTheDocument();
  expect(screen.getByText(/5 of 50 shared photos/)).toBeInTheDocument();
});
