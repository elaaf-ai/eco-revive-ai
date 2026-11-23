import { Check, GraduationCap, X } from "lucide-react";
import { useId, useState } from "react";
import { ApiError, sendFeedback } from "../api";
import { blobToBase64 } from "../frames";
import { itemNumber, type Detection } from "../types";

type State = { status: "idle" } | { status: "sending" } | { status: "sent"; photo: boolean } | { status: "error"; message: string };

/**
 * Adaptive learning: the user says whether a detected item was right. With consent, the photo is
 * kept as training data; the next model is trained on it and goes live only if it scores better.
 */
export function Feedback({
  detection,
  modelVersion,
  scanId,
  photo,
  announce,
}: {
  detection: Detection;
  modelVersion: string;
  scanId?: string | null;
  photo?: Blob;
  announce: (message: string) => void;
}) {
  const [share, setShare] = useState(false);
  const [state, setState] = useState<State>({ status: "idle" });
  const shareId = useId();
  const label = `Plastic ${itemNumber(detection)}${detection.item_name ? ` (${detection.item_name})` : ""}`;

  const send = async (correct: boolean) => {
    setState({ status: "sending" });
    try {
      const image = share && photo ? await blobToBase64(photo) : undefined;
      const result = await sendFeedback({
        correct,
        class_name: detection.class_name,
        confidence: detection.confidence,
        box: detection.box,
        model_version: modelVersion,
        item_name: detection.item_name ?? null,
        scan_id: scanId ?? null,
        share_photo: Boolean(image),
        ...(image ? { image } : {}),
      });
      setState({ status: "sent", photo: result.photo_saved });
      announce("Thanks. Your answer will help train the next model.");
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Could not send your answer.";
      setState({ status: "error", message });
      announce(message);
    }
  };

  if (state.status === "sent") {
    return (
      <p className="feedback feedback-done" role="status">
        <GraduationCap size={18} aria-hidden /> Thanks! {state.photo ? "Your photo and answer" : "Your answer"} will help
        train the next model.
      </p>
    );
  }

  return (
    <div className="feedback" role="group" aria-label={`Was ${label} right?`}>
      <p className="feedback-question">
        <GraduationCap size={18} aria-hidden /> Was {label} right?
      </p>
      <div className="feedback-actions">
        <button type="button" className="btn btn-ghost" disabled={state.status === "sending"} onClick={() => void send(true)}>
          <Check size={16} aria-hidden /> Yes
        </button>
        <button type="button" className="btn btn-ghost" disabled={state.status === "sending"} onClick={() => void send(false)}>
          <X size={16} aria-hidden /> No, it's wrong
        </button>
      </div>
      {photo && (
        <label className="feedback-share" htmlFor={shareId}>
          <input id={shareId} type="checkbox" checked={share} onChange={(event) => setShare(event.target.checked)} />
          <span>Share this photo to help train the model. It is stored without location data; clearing your history deletes it.</span>
        </label>
      )}
      {state.status === "error" && <p className="notice notice-error">{state.message}</p>}
    </div>
  );
}
