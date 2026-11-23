import { BadgeCheck, HelpCircle, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { ApiError, fetchGuide } from "../api";
import { CLASS_META, percent } from "../classes";
import { cropToBase64 } from "../frames";
import { WASTE_CLASSES, type DetectResponse, type Guide, type WasteClass } from "../types";
import { GuideCard } from "./GuideCard";

type GuideState =
  | { status: "idle" }
  | { status: "confirm"; reason: string }
  | { status: "loading" }
  | { status: "ready"; guide: Guide; cached: boolean; item: string | null }
  | { status: "error"; message: string };

interface ResultsPanelProps {
  result: DetectResponse;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onRetake: () => void;
  announce: (message: string) => void;
  enabled?: WasteClass[];
  /** The scanned photo. A crop of the selected item is sent so the guide fits the real item. */
  photo?: Blob;
}

const HINTS: Record<string, string> = {
  too_dark: "The photo is dark. Add light.",
  too_bright: "The photo is very bright. Avoid direct glare.",
  blurry: "The photo looks blurry. Hold still and tap to focus.",
  small: "The photo is small. Move closer to the item.",
};

export function ResultsPanel({
  result,
  selectedId,
  onSelect,
  onRetake,
  announce,
  enabled = [...WASTE_CLASSES],
  photo,
}: ResultsPanelProps) {
  const single = enabled.length === 1 ? enabled[0] : undefined;
  const selected = result.detections.find((d) => d.id === selectedId) ?? null;
  const verdict = result.verdict ?? null;
  // The Gemini vision check is an independent second opinion. When it confirms plastic, the user
  // does not need to confirm the material by hand.
  const aiConfirmed = Boolean(verdict?.contains_plastic && verdict.gemini === "plastic");
  const aiRejected = Boolean(verdict && !verdict.contains_plastic && verdict.gemini === "no_plastic");
  const uncertain =
    !aiConfirmed && (result.quality.status === "low_confidence" || result.quality.status === "ambiguous" || aiRejected);
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
      setGuide({ status: "confirm", reason: aiRejected && verdict ? verdict.message : result.quality.message });
    } else {
      setRequest({ cls: selected.class_name, confirmed: aiConfirmed });
      setGuide({ status: "loading" });
    }
  }

  useEffect(() => {
    if (!request || !selected) return;
    const controller = new AbortController();
    const crop = photo ? cropToBase64(photo, selected.box).catch(() => undefined) : Promise.resolve(undefined);
    crop
      .then((image) =>
        fetchGuide(
          {
            class_name: request.cls,
            confidence: selected.confidence,
            confirmed_by_user: request.confirmed,
            ...(image ? { image } : {}),
            ...(image && verdict?.plastic_items.length ? { context_items: verdict.plastic_items } : {}),
          },
          controller.signal,
        ),
      )
      .then((response) => {
        setGuide({
          status: "ready",
          guide: response.guide,
          cached: response.cached,
          item: response.identified_item ?? null,
        });
        announce(
          response.identified_item
            ? `Identified ${response.identified_item}. Guide ready: ${response.guide.title}`
            : `Guide ready: ${response.guide.title}`,
        );
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
  }, [request, selected, announce, photo, verdict]);

  if (result.detections.length === 0) {
    const aiSeesPlastic = verdict?.contains_plastic && verdict.gemini === "plastic";
    return (
      <div className="panel-empty">
        <HelpCircle size={28} aria-hidden />
        <h2>{aiSeesPlastic ? "Plastic seen, but not boxed" : "Nothing recognised"}</h2>
        <p>{aiSeesPlastic && verdict ? verdict.message : result.quality.message}</p>
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

      {verdict && verdict.gemini !== "not_asked" && verdict.gemini !== "unavailable" && (
        <p className={`notice ${verdict.contains_plastic ? "notice-ok" : "notice-warn"}`} data-testid="verdict">
          {verdict.contains_plastic ? <BadgeCheck size={18} aria-hidden /> : <HelpCircle size={18} aria-hidden />}
          <span>{verdict.message}</span>
        </p>
      )}
      {uncertain && !aiRejected && <p className="notice notice-warn">{result.quality.message}</p>}
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
                <span className="detection-name">
                  {detection.class_name}
                  {aiConfirmed && (
                    <span className="detection-check">
                      <BadgeCheck size={14} aria-hidden /> AI-checked
                    </span>
                  )}
                </span>
                <span className="detection-conf" title="Detector confidence">
                  {percent(detection.confidence)}
                </span>
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
            <legend>{single ? `Is this item ${single.toLowerCase()}?` : "What is this item made of?"}</legend>
            {!uncertain && <p className="muted">{guide.reason}</p>}
            <div className="material-options" role="radiogroup" hidden={Boolean(single)}>
              {enabled.map((cls) => (
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
              {single ? `Yes, it's ${single.toLowerCase()}` : `Show guide for ${material ?? "this item"}`}
            </button>
            {single && (
              <button type="button" className="btn btn-ghost" onClick={onRetake}>
                No, retake photo
              </button>
            )}
          </div>
        </form>
      )}

      {selected && guide.status === "loading" && (
        <p className="loading" role="status">
          <Loader2 className="spin" size={18} aria-hidden /> Preparing the guide…
        </p>
      )}
      {selected && guide.status === "error" && <p className="notice notice-error">{guide.message}</p>}
      {selected && guide.status === "ready" && guide.item && (
        <p className="identified" data-testid="identified-item">
          <Sparkles size={16} aria-hidden /> Identified as <strong>{guide.item}</strong>
        </p>
      )}
      {selected && guide.status === "ready" && <GuideCard guide={guide.guide} cached={guide.cached} />}
    </div>
  );
}
