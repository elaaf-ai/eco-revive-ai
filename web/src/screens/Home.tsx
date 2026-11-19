import { ArrowRight, Camera, ImageUp, ShieldCheck } from "lucide-react";
import { CLASS_META } from "../classes";
import { WASTE_CLASSES } from "../types";

export function Home({ onStart }: { onStart: () => void }) {
  return (
    <div className="home">
      <section className="hero">
        <p className="eyebrow">Waste scanner</p>
        <h1>
          Point. Scan. <span className="accent">Give it a second life.</span>
        </h1>
        <p className="lede">
          EcoRevive spots plastic, glass, metal, organic and hazardous waste in a photo, then shows you a short reuse
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

      <section className="class-grid" aria-labelledby="classes-title">
        <h2 id="classes-title" className="section-title">
          What it recognises
        </h2>
        <ul>
          {WASTE_CLASSES.map((cls) => (
            <li key={cls} className="class-card" style={{ ["--box-color" as string]: CLASS_META[cls].color }}>
              <span className="class-dot" aria-hidden />
              <strong>{cls}</strong>
              <span>{CLASS_META[cls].blurb}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="safety" aria-labelledby="safety-title">
        <ShieldCheck size={22} aria-hidden />
        <div>
          <h2 id="safety-title">A scan is a guess, not a safety check</h2>
          <p>
            A photo can't tell whether something is broken, sharp or contains chemicals. Check the item yourself.
            Batteries and aerosols always get disposal steps, never craft projects.
          </p>
        </div>
      </section>
    </div>
  );
}
