import { HelpCircle, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { ApiError, fetchGuide } from "../api";
import { CLASS_META, percent } from "../classes";
import { WASTE_CLASSES, type DetectResponse, type Guide, type WasteClass } from "../types";
import { GuideCard } from "./GuideCard";

type GuideState =
  | { status: "idle" }
  | { status: "confirm"; reason: string }
  | { status: "loading" }
  | { status: "ready"; guide: Guide; cached: boolean }
  | { status: "error"; message: string };

interface ResultsPanelProps {
  result: DetectResponse;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onRetake: () => void;
  announce: (message: string) => void;
}

const HINTS: Record<string, string> = {
  too_dark: "The photo is dark. Add light.",
  too_bright: "The photo is very bright. Avoid direct glare.",
  blurry: "The photo looks blurry. Hold still and tap to focus.",
  small: "The photo is small. Move closer to the item.",
};

export function ResultsPanel({ result, selectedId, onSelect, onRetake, announce }: ResultsPanelProps) {
  const selected = result.detections.find((d) => d.id === selectedId) ?? null;
  const uncertain = result.quality.status === "low_confidence" || result.quality.status === "ambiguous";
  const [guide, setGuide] = useState<GuideState>({ status: "idle" });
  const [material, setMaterial] = useState<WasteClass | null>(null);
  const [request, setRequest] = useState<{ cls: WasteClass; confirmed: boolean } | null>(null);
  const groupId = useId();

  // Choosing a detection decides whether a guide can load directly or needs confirmation.
  const [lastSelected, setLastSelected] = useState<number | null>(null);
  if (selected && selected.id !== lastSelected) {
    setLastSelected(selected.id);
    setMaterial(selected.class_name);
    if (uncertain) {
      setRequest(null);
      setGuide({ status: "confirm", reason: result.quality.message });
    } else {
      setRequest({ cls: selected.class_name, confirmed: false });
      setGuide({ status: "loading" });
    }
  }

  useEffect(() => {
    if (!request || !selected) return;
    const controller = new AbortController();
    fetchGuide(
      { class_name: request.cls, confidence: selected.confidence, confirmed_by_user: request.confirmed },
      controller.signal,
    )
      .then((response) => {
        setGuide({ status: "ready", guide: response.guide, cached: response.cached });
        announce(`Guide ready: ${response.guide.title}`);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.code === "confirmation_required") {
          setGuide({ status: "confirm", reason: error.message });
          announce("Please confirm the material.");
        } else {
          const message = error instanceof ApiError ? error.message : "The guide could not load.";
          setGuide({ status: "error", message });
          announce(message);
        }
      });
    return () => controller.abort();
  }, [request, selected, announce]);

  if (result.detections.length === 0) {
    return (
      <div className="panel-empty">
        <HelpCircle size={28} aria-hidden />
        <h2>Nothing recognised</h2>
        <p>{result.quality.message}</p>
        {result.quality.image_hints.map((hint) => (
          <p key={hint} className="hint">
            {HINTS[hint]}
          </p>
        ))}
        <button type="button" className="btn btn-primary" onClick={onRetake}>
          <RotateCcw size={18} aria-hidden /> Retake
        </button>
      </div>
    );
  }

  return (
    <div className="results">
      <div className="results-head">
        <h2>
          {result.detections.length} {result.detections.length === 1 ? "item" : "items"} found
        </h2>
        <button type="button" className="btn btn-ghost" onClick={onRetake}>
          <RotateCcw size={16} aria-hidden /> Retake
        </button>
      </div>

      {uncertain && <p className="notice notice-warn">{result.quality.message}</p>}
      {result.quality.image_hints.map((hint) => (
        <p key={hint} className="hint">
          {HINTS[hint]}
        </p>
      ))}

      <ul className="detections" aria-label="Detected items">
        {result.detections.map((detection) => {
          const meta = CLASS_META[detection.class_name];
          const active = detection.id === selectedId;
          return (
            <li key={detection.id}>
              <button
                type="button"
                className={`detection${active ? " is-active" : ""}`}
                aria-pressed={active}
                onClick={() => onSelect(detection.id)}
                style={{ ["--box-color" as string]: meta.color }}
              >
                <span className="detection-swatch" aria-hidden>
                  {meta.short}
                </span>
                <span className="detection-name">{detection.class_name}</span>
                <span className="detection-conf">{percent(detection.confidence)}</span>
              </button>
            </li>
          );
        })}
      </ul>

      {!selected && <p className="muted">Select an item to see its guide.</p>}

      {selected && guide.status === "confirm" && (
        <form
          className="confirm"
          onSubmit={(event) => {
            event.preventDefault();
            if (!material) return;
            setRequest({ cls: material, confirmed: true });
            setGuide({ status: "loading" });
          }}
        >
          <fieldset>
            <legend>What is this item made of?</legend>
            {!uncertain && <p className="muted">{guide.reason}</p>}
            <div className="material-options" role="radiogroup">
              {WASTE_CLASSES.map((cls) => (
                <label key={cls} className="material-option" style={{ ["--box-color" as string]: CLASS_META[cls].color }}>
                  <input
                    type="radio"
                    name={groupId}
                    value={cls}
                    checked={material === cls}
                    onChange={() => setMaterial(cls)}
                  />
                  <span>{cls}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="confirm-actions">
            <button type="submit" className="btn btn-primary" disabled={!material}>
              Show guide for {material ?? "this item"}
            </button>
          </div>
        </form>
      )}

      {selected && guide.status === "loading" && (
        <p className="loading" role="status">
          <Loader2 className="spin" size={18} aria-hidden /> Preparing the guide…
        </p>
      )}
      {selected && guide.status === "error" && <p className="notice notice-error">{guide.message}</p>}
      {selected && guide.status === "ready" && <GuideCard guide={guide.guide} cached={guide.cached} />}
    </div>
  );
}
