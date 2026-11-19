import { Loader2, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError, fetchGuide } from "../api";
import type { Guide, WasteClass } from "../types";
import { GuideCard } from "./GuideCard";

type State =
  | { status: "idle" }
  | { status: "loading"; query: string }
  | { status: "ready"; guide: Guide; cached: boolean; query: string }
  | { status: "error"; message: string };

const EXAMPLES = ["water bottle", "yogurt cup", "shampoo bottle", "plastic bag"];

/** Type an item name to get a guide without scanning. */
export function GuideSearch({
  material,
  announce,
}: {
  material: WasteClass;
  announce: (message: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });
  const controller = useRef<AbortController | null>(null);
  const inputId = useId();
  useEffect(() => () => controller.current?.abort(), []);

  const search = async (raw: string) => {
    const text = raw.trim().slice(0, 60);
    if (!text) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setState({ status: "loading", query: text });
    announce(`Finding a guide for ${text}…`);
    try {
      const response = await fetchGuide(
        { class_name: material, confidence: 1, confirmed_by_user: true, item_hint: text },
        current.signal,
      );
      setState({ status: "ready", guide: response.guide, cached: response.cached, query: text });
      announce(`Guide ready: ${response.guide.title}`);
    } catch (error) {
      if (current.signal.aborted) return;
      const message = error instanceof ApiError ? error.message : "The guide could not load. Try again.";
      setState({ status: "error", message });
      announce(message);
    }
  };

  return (
    <section className="search" aria-labelledby={`${inputId}-title`}>
      <h2 id={`${inputId}-title`} className="search-title">
        Search a {material.toLowerCase()} item
      </h2>
      <form
        role="search"
        className="search-form"
        onSubmit={(event) => {
          event.preventDefault();
          void search(query);
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          {material} item name
        </label>
        <Search size={18} aria-hidden className="search-icon" />
        <input
          id={inputId}
          type="search"
          value={query}
          maxLength={60}
          placeholder={`e.g. ${EXAMPLES[0]}`}
          autoComplete="off"
          enterKeyHint="search"
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="submit" className="btn btn-primary" disabled={!query.trim() || state.status === "loading"}>
          Get guide
        </button>
      </form>
      <div className="search-examples" aria-label="Examples">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="chip-button"
            onClick={() => {
              setQuery(example);
              void search(example);
            }}
          >
            {example}
          </button>
        ))}
      </div>
      {state.status === "loading" && (
        <p className="loading" role="status">
          <Loader2 className="spin" size={18} aria-hidden /> Finding a guide for “{state.query}”…
        </p>
      )}
      {state.status === "error" && <p className="notice notice-error">{state.message}</p>}
      {state.status === "ready" && (
        <>
          <p className="muted small">Guide for “{state.query}”. Check the item yourself before starting.</p>
          <GuideCard guide={state.guide} cached={state.cached} />
        </>
      )}
    </section>
  );
}
