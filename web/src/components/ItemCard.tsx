import { AlertTriangle, Loader2, Recycle, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError, fetchGuide } from "../api";
import type { CatalogItem, Guide, WasteClass } from "../types";
import { GuideCard } from "./GuideCard";

/** Recycling and upcycling methods for one coded item, plus an optional AI idea. */
export function ItemCard({
  item,
  material,
  announce,
  aiAvailable = false,
}: {
  item: CatalogItem;
  material: WasteClass;
  announce: (message: string) => void;
  aiAvailable?: boolean;
}) {
  const variant = useRef(0);
  const [extra, setExtra] = useState<
    { status: "idle" } | { status: "loading" } | { status: "ready"; guide: Guide } | { status: "error"; message: string }
  >({ status: "idle" });
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const moreIdeas = async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setExtra({ status: "loading" });
    variant.current = (variant.current % 9) + 1;
    try {
      const response = await fetchGuide(
        {
          class_name: material,
          confidence: 1,
          confirmed_by_user: true,
          item_hint: item.name,
          variant: variant.current,
        },
        current.signal,
      );
      setExtra({ status: "ready", guide: response.guide });
      announce(`Another idea: ${response.guide.title}`);
    } catch (error) {
      if (current.signal.aborted) return;
      setExtra({ status: "error", message: error instanceof ApiError ? error.message : "Could not load another idea." });
    }
  };

  return (
    <article className="item-card" aria-labelledby={`item-${item.code}`}>
      <header className="item-head">
        <span className="item-code" aria-label={`Item code ${item.code}`}>
          {item.code}
        </span>
        <div>
          <h3 id={`item-${item.code}`}>{item.name}</h3>
          <p className="muted small">
            Resin {item.resin.number} · {item.resin.type}
          </p>
        </div>
      </header>

      <section className="item-section">
        <h4>
          <Recycle size={16} aria-hidden /> Recycling
        </h4>
        <p className="muted">{item.recycling.accepted}</p>
        <ol className="steps">
          {item.recycling.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <section className="item-section">
        <h4>
          <Sparkles size={16} aria-hidden /> Upcycling: {item.upcycling.title}
        </h4>
        <ul className="chips" aria-label="You need">
          {item.upcycling.materials.map((material) => (
            <li key={material}>{material}</li>
          ))}
        </ul>
        <ol className="steps">
          {item.upcycling.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        {item.upcycling.precautions.length > 0 && (
          <div className="precautions">
            <h4>
              <AlertTriangle size={16} aria-hidden /> Precautions
            </h4>
            <ul>
              {item.upcycling.precautions.map((precaution) => (
                <li key={precaution}>{precaution}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <p className="safety-notice">
        Recycling rules differ between areas, so check your council's list. {item.safety_notice}
      </p>

      {extra.status === "loading" && (
        <p className="loading" role="status">
          <Loader2 className="spin" size={18} aria-hidden /> Thinking of another idea…
        </p>
      )}
      {extra.status === "error" && <p className="notice notice-error">{extra.message}</p>}
      {extra.status === "ready" && <GuideCard guide={extra.guide} cached={false} />}
      {aiAvailable && extra.status !== "loading" && (
        <button type="button" className="btn btn-ghost" onClick={() => void moreIdeas()}>
          <Sparkles size={16} aria-hidden /> {extra.status === "ready" ? "Show a different idea" : "Another upcycling idea"}
        </button>
      )}
    </article>
  );
}
