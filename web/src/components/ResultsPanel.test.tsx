import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import type { DetectResponse, Guide } from "../types";
import { ResultsPanel } from "./ResultsPanel";

const guide = (overrides: Partial<Guide> = {}): Guide => ({
  class_name: "Plastic",
  kind: "upcycle",
  title: "Bottle planter",
  materials: ["Bottle"],
  steps: ["One.", "Two.", "Three."],
  precautions: ["Careful."],
  source: "curated",
  source_detail: "Gemini is not configured on this server.",
  safety_notice: "A photo cannot confirm what an item contains or that it is safe to handle.",
  ...overrides,
});

const result = (status: DetectResponse["quality"]["status"], detections: DetectResponse["detections"]): DetectResponse => ({
  api_version: "1",
  request_id: "req-1",
  model: {
    version: "0.1.0-preview",
    status: "preview",
    format: "onnx",
    classes: ["Plastic", "Glass", "Metal", "Organic", "Hazardous"],
    enabled_classes: ["Plastic", "Glass", "Metal", "Organic", "Hazardous"],
  },
  image: { width: 640, height: 480 },
  detections,
  quality: { status, message: status === "ok" ? "Select an item." : "The scan is not sure.", image_hints: [] },
  inference_ms: 40,
});

const plastic = { id: 0, class_id: 0, class_name: "Plastic" as const, confidence: 0.91, box: { x1: 0.1, y1: 0.1, x2: 0.5, y2: 0.5 } };

afterEach(() => vi.restoreAllMocks());

function mockGuide(body: Guide) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ api_version: "1", request_id: "g", guide: body, cached: false }), { status: 200 }),
  );
}

it("loads and labels the guide for a confident detection", async () => {
  const fetchMock = mockGuide(guide());
  render(<ResultsPanel result={result("ok", [plastic])} selectedId={0} onSelect={() => {}} onRetake={() => {}} announce={() => {}} />);
  expect(await screen.findByRole("heading", { name: "Bottle planter" })).toBeInTheDocument();
  expect(screen.getByText(/Curated guide · Gemini is not configured/)).toBeInTheDocument();
  expect(screen.getByText(/cannot confirm/)).toBeInTheDocument();
  const body = JSON.parse(String(fetchMock.mock.calls[0]![1]!.body));
  expect(body).toMatchObject({ class_name: "Plastic", confirmed_by_user: false });
});

it("asks for confirmation before showing a guide for an uncertain scan", async () => {
  const fetchMock = mockGuide(guide({ class_name: "Glass", title: "Jar storage" }));
  const low = { ...plastic, confidence: 0.32 };
  render(<ResultsPanel result={result("low_confidence", [low])} selectedId={0} onSelect={() => {}} onRetake={() => {}} announce={() => {}} />);
  expect(screen.getByRole("group", { name: "What is this item made of?" })).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();

  await userEvent.click(screen.getByRole("radio", { name: "Glass" }));
  await userEvent.click(screen.getByRole("button", { name: "Show guide for Glass" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const body = JSON.parse(String(fetchMock.mock.calls[0]![1]!.body));
  expect(body).toMatchObject({ class_name: "Glass", confirmed_by_user: true });
  expect(await screen.findByRole("heading", { name: "Jar storage" })).toBeInTheDocument();
});

it("asks a yes/no plastic question in plastic-only mode", async () => {
  const fetchMock = mockGuide(guide());
  const onRetake = vi.fn();
  const low = { ...plastic, confidence: 0.32 };
  render(
    <ResultsPanel
      result={result("low_confidence", [low])}
      selectedId={0}
      onSelect={() => {}}
      onRetake={onRetake}
      announce={() => {}}
      enabled={["Plastic"]}
    />,
  );
  expect(screen.getByRole("group", { name: "Is this item plastic?" })).toBeInTheDocument();
  expect(screen.queryByRole("radio", { name: "Glass" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "No, retake photo" }));
  expect(onRetake).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Yes, it's plastic" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(JSON.parse(String(fetchMock.mock.calls[0]![1]!.body))).toMatchObject({
    class_name: "Plastic",
    confirmed_by_user: true,
  });
});

it("shows hazardous guidance as safe disposal", async () => {
  mockGuide(guide({ class_name: "Hazardous", kind: "disposal", title: "Take it to a collection point" }));
  const hazard = { ...plastic, class_id: 4, class_name: "Hazardous" as const };
  render(<ResultsPanel result={result("ok", [hazard])} selectedId={0} onSelect={() => {}} onRetake={() => {}} announce={() => {}} />);
  expect(await screen.findByText("Safe disposal")).toBeInTheDocument();
});

it("shows the empty state with a retake action", async () => {
  const onRetake = vi.fn();
  render(<ResultsPanel result={result("no_detections", [])} selectedId={null} onSelect={() => {}} onRetake={onRetake} announce={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "Retake" }));
  expect(onRetake).toHaveBeenCalled();
});

it("lets the user choose between several detections", async () => {
  const onSelect = vi.fn();
  const glass = { ...plastic, id: 1, class_id: 1, class_name: "Glass" as const, confidence: 0.7 };
  render(<ResultsPanel result={result("ok", [plastic, glass])} selectedId={null} onSelect={onSelect} onRetake={() => {}} announce={() => {}} />);
  expect(screen.getByText("2 items found")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Glass/ }));
  expect(onSelect).toHaveBeenCalledWith(1);
});

describe("Gemini vision second opinion", () => {
  const weak = { ...plastic, confidence: 0.27 };
  const verdict = (contains: boolean, items: string[] = []) => ({
    contains_plastic: contains,
    rule: "gemini" as const,
    decided_by: "gemini" as const,
    detector_score: 0.27,
    gemini: contains ? ("plastic" as const) : ("no_plastic" as const),
    plastic_items: items,
    message: contains ? `Plastic confirmed by the AI check: ${items.join(", ")}.` : "The AI check does not see plastic here, so the detector's box may be wrong.",
  });

  it("numbers and names each AI-checked box and uses its name for the guide", async () => {
    const fetchMock = mockGuide(guide({ title: "Glasses frame keyring" }));
    const named = { ...weak, item_name: "glasses frame", ai_checked: true };
    const scan = {
      ...result("low_confidence", [named]),
      verdict: verdict(true, ["glasses frame"]),
      ai_removed: ["person", "wall"],
    };
    render(<ResultsPanel result={scan} selectedId={0} onSelect={() => {}} onRetake={() => {}} announce={() => {}} enabled={["Plastic"]} />);
    expect(screen.getByTestId("verdict")).toHaveTextContent("Plastic confirmed by the AI check: glasses frame.");
    expect(screen.getByRole("button", { name: /Plastic 1\s*glasses frame\s*AI-checked/ })).toBeInTheDocument();
    expect(screen.getByTestId("ai-removed")).toHaveTextContent("removed 2 boxes that were not plastic (person, wall)");
    expect(await screen.findByRole("heading", { name: "Glasses frame keyring" })).toBeInTheDocument();
    expect(screen.queryByText("Is this item plastic?")).not.toBeInTheDocument();
    const body = JSON.parse(String(fetchMock.mock.calls[0]![1]!.body));
    expect(body.confirmed_by_user).toBe(true);
    expect(body.item_hint).toBe("glasses frame");
  });

  it("a photo-level confirmation alone does not mark unchecked boxes", () => {
    mockGuide(guide());
    const scan = { ...result("low_confidence", [weak]), verdict: verdict(true, ["plastic cup"]) };
    render(<ResultsPanel result={scan} selectedId={0} onSelect={() => {}} onRetake={() => {}} announce={() => {}} enabled={["Plastic"]} />);
    expect(screen.queryByText("AI-checked")).not.toBeInTheDocument();
    expect(screen.getByText("Is this item plastic?")).toBeInTheDocument();
  });

  it("offers guides for items the AI saw but the detector did not box", async () => {
    const fetchMock = mockGuide(guide({ title: "Cup seed starter" }));
    const scan = { ...result("no_detections", []), verdict: verdict(true, ["plastic cup", "straw"]), ai_removed: ["person"] };
    render(<ResultsPanel result={scan} selectedId={null} onSelect={() => {}} onRetake={() => {}} announce={() => {}} enabled={["Plastic"]} />);
    expect(screen.getByRole("heading", { name: "Plastic seen, but not boxed" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Guide for plastic cup" }));
    expect(await screen.findByRole("heading", { name: "Cup seed starter" })).toBeInTheDocument();
    expect(JSON.parse(String(fetchMock.mock.calls[0]![1]!.body)).item_hint).toBe("plastic cup");
  });

  it("asks the user when the AI check does not see plastic", () => {
    mockGuide(guide());
    const scan = { ...result("ok", [plastic]), verdict: verdict(false) };
    render(<ResultsPanel result={scan} selectedId={0} onSelect={() => {}} onRetake={() => {}} announce={() => {}} enabled={["Plastic"]} />);
    expect(screen.getByTestId("verdict")).toHaveTextContent("does not see plastic");
    expect(screen.getByText("Is this item plastic?")).toBeInTheDocument();
  });

  it("shows the item the AI identified from the crop", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ api_version: "1", request_id: "g", guide: guide({ title: "Frame photo holder" }), cached: false, identified_item: "glasses frame" }),
        { status: 200 },
      ),
    );
    render(<ResultsPanel result={result("ok", [plastic])} selectedId={0} onSelect={() => {}} onRetake={() => {}} announce={() => {}} />);
    expect(await screen.findByTestId("identified-item")).toHaveTextContent("Identified as glasses frame");
  });
});
