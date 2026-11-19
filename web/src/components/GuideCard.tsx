import { AlertTriangle, BookOpenCheck, ShieldAlert, Sparkles } from "lucide-react";
import type { Guide } from "../types";

export function GuideCard({ guide, cached }: { guide: Guide; cached: boolean }) {
  const disposal = guide.kind === "disposal";
  return (
    <article className={`guide${disposal ? " is-disposal" : ""}`} aria-labelledby="guide-title">
      <header className="guide-head">
        <p className="eyebrow">
          {disposal ? <ShieldAlert size={16} aria-hidden /> : <Sparkles size={16} aria-hidden />}
          {disposal ? "Safe disposal" : "Upcycling idea"}
        </p>
        <h3 id="guide-title">{guide.title}</h3>
        <p className="guide-source">
          <BookOpenCheck size={14} aria-hidden />
          {guide.source === "gemini" ? "AI-generated" : "Curated guide"} · {guide.source_detail}
          {cached ? " · saved copy" : ""}
        </p>
      </header>

      <section>
        <h4>You need</h4>
        <ul className="chips">
          {guide.materials.map((material) => (
            <li key={material}>{material}</li>
          ))}
        </ul>
      </section>

      <section>
        <h4>Steps</h4>
        <ol className="steps">
          {guide.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      {guide.precautions.length > 0 && (
        <section className="precautions">
          <h4>
            <AlertTriangle size={16} aria-hidden /> Precautions
          </h4>
          <ul>
            {guide.precautions.map((precaution) => (
              <li key={precaution}>{precaution}</li>
            ))}
          </ul>
        </section>
      )}

      <p className="safety-notice">{guide.safety_notice}</p>
    </article>
  );
}
