import { ArrowRight, Camera, ImageUp, ShieldCheck } from "lucide-react";
import { CLASS_META } from "../classes";
import { GuideSearch } from "../components/GuideSearch";
import type { WasteClass } from "../types";

function listWords(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

export function Home({
  onStart,
  enabled,
  announce,
}: {
  onStart: () => void;
  enabled: WasteClass[];
  announce: (message: string) => void;
}) {
  const single = enabled.length === 1 ? enabled[0] : undefined;
  return (
    <div className="home">
      <section className="hero">
        <p className="eyebrow">{single ? `${single} scanner` : "Waste scanner"}</p>
        <h1>
          Point. Scan. <span className="accent">Give it a second life.</span>
        </h1>
        <p className="lede">
          EcoRevive spots {listWords(enabled.map((c) => c.toLowerCase()))} waste in a photo, then shows you a short reuse
          project or how to throw it away safely.
        </p>
        <div className="hero-actions">
          <button type="button" className="btn btn-primary btn-lg" onClick={onStart}>
            <Camera size={20} aria-hidden /> Start a scan <ArrowRight size={18} aria-hidden />
          </button>
          <p className="muted small">
            <ImageUp size={14} aria-hidden /> No camera? You can upload a photo on the next screen.
          </p>
        </div>
      </section>

      {single ? (
        <GuideSearch material={single} announce={announce} />
      ) : (
        <section className="class-grid" aria-labelledby="classes-title">
          <h2 id="classes-title" className="section-title">
            What it recognises
          </h2>
          <ul>
            {enabled.map((cls) => (
              <li key={cls} className="class-card" style={{ ["--box-color" as string]: CLASS_META[cls].color }}>
                <span className="class-dot" aria-hidden />
                <strong>{cls}</strong>
                <span>{CLASS_META[cls].blurb}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="safety" aria-labelledby="safety-title">
        <ShieldCheck size={22} aria-hidden />
        <div>
          <h2 id="safety-title">A scan is a guess, not a safety check</h2>
          <p>
            A photo can't tell whether something is broken, sharp or contains chemicals. Check the item yourself before
            you reuse it.
          </p>
        </div>
      </section>
    </div>
  );
}
