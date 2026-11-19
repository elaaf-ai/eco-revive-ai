import { Loader2, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError, fetchGuide, fetchItem, fetchItems, matchItems } from "../api";
import type { CatalogItem, Guide, ItemSummary, WasteClass } from "../types";
import { GuideCard } from "./GuideCard";
import { ItemCard } from "./ItemCard";

type State =
  | { status: "idle" }
  | { status: "loading"; label: string }
  | { status: "item"; item: CatalogItem }
  | { status: "choose"; matches: ItemSummary[] }
  | { status: "guide"; guide: Guide; cached: boolean; query: string }
  | { status: "error"; message: string };

/** Search by item code (e.g. 001) or name. Codes open the item's recycling and upcycling methods. */
export function GuideSearch({ material, announce }: { material: WasteClass; announce: (message: string) => void }) {
  const [items, setItems] = useState<ItemSummary[]>([]);
  const [query, setQuery] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });
  const controller = useRef<AbortController | null>(null);
  const inputId = useId();

  useEffect(() => {
    const load = new AbortController();
    fetchItems(load.signal)
      .then(setItems)
      .catch(() => undefined);
    return () => {
      load.abort();
      controller.current?.abort();
    };
  }, []);

  const begin = (label: string) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setState({ status: "loading", label });
    return current;
  };

  const openItem = async (summary: ItemSummary) => {
    setQuery(summary.code);
    const current = begin(`${summary.code} ${summary.name}`);
    try {
      const item = await fetchItem(summary.code, current.signal);
      setState({ status: "item", item });
      announce(`Item ${item.code}, ${item.name}: recycling and upcycling methods shown.`);
    } catch (error) {
      if (current.signal.aborted) return;
      setState({ status: "error", message: error instanceof ApiError ? error.message : "Could not load the item." });
    }
  };

  const aiGuide = async (text: string) => {
    const current = begin(text);
    try {
      const response = await fetchGuide(
        { class_name: material, confidence: 1, confirmed_by_user: true, item_hint: text },
        current.signal,
      );
      setState({ status: "guide", guide: response.guide, cached: response.cached, query: text });
      announce(`Guide ready: ${response.guide.title}`);
    } catch (error) {
      if (current.signal.aborted) return;
      setState({ status: "error", message: error instanceof ApiError ? error.message : "The guide could not load." });
    }
  };

  const submit = (raw: string) => {
    const text = raw.trim().slice(0, 60);
    if (!text) return;
    const matches = matchItems(items, text);
    const isCode = /^#?\d{1,3}$/.test(text);
    if (matches.length === 1 || (isCode && matches[0]?.code === text.replace(/^#/, "").padStart(3, "0"))) {
      void openItem(matches[0]!);
    } else if (matches.length > 1) {
      setState({ status: "choose", matches });
      announce(`${matches.length} items match. Choose one.`);
    } else if (isCode) {
      const message = `No item has the code ${text}. See the list of codes below.`;
      setState({ status: "error", message });
      announce(message);
    } else {
      void aiGuide(text);
    }
  };

  const suggestions = state.status === "loading" || state.status === "item" ? [] : matchItems(items, query).slice(0, 5);

  return (
    <section className="search" aria-labelledby={`${inputId}-title`}>
      <h2 id={`${inputId}-title`} className="search-title">
        Search by item code or name
      </h2>
      <form
        role="search"
        className="search-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(query);
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          Item code or name
        </label>
        <Search size={18} aria-hidden className="search-icon" />
        <input
          id={inputId}
          type="search"
          value={query}
          maxLength={60}
          placeholder="e.g. 001 or water bottle"
          autoComplete="off"
          enterKeyHint="search"
          onChange={(event) => {
            setQuery(event.target.value);
            if (state.status !== "loading") setState({ status: "idle" });
          }}
        />
        <button type="submit" className="btn btn-primary" disabled={!query.trim() || state.status === "loading"}>
          Search
        </button>
      </form>

      {query.trim() && suggestions.length > 0 && state.status !== "choose" && (
        <ul className="suggestions" aria-label="Matching items">
          {suggestions.map((item) => (
            <li key={item.code}>
              <button type="button" className="suggestion" onClick={() => void openItem(item)}>
                <span className="item-code small-code">{item.code}</span>
                {item.name}
              </button>
            </li>
          ))}
        </ul>
      )}

      {state.status === "choose" && (
        <ul className="suggestions" aria-label="Choose an item">
          {state.matches.map((item) => (
            <li key={item.code}>
              <button type="button" className="suggestion" onClick={() => void openItem(item)}>
                <span className="item-code small-code">{item.code}</span>
                {item.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      {state.status === "loading" && (
        <p className="loading" role="status">
          <Loader2 className="spin" size={18} aria-hidden /> Looking up “{state.label}”…
        </p>
      )}
      {state.status === "error" && <p className="notice notice-error">{state.message}</p>}
      {state.status === "item" && <ItemCard item={state.item} material={material} announce={announce} />}
      {state.status === "guide" && (
        <>
          <p className="muted small">
            No coded item matches “{state.query}”, so here is a general guide. Check the item yourself before starting.
          </p>
          <GuideCard guide={state.guide} cached={state.cached} />
        </>
      )}

      {items.length > 0 && (
        <details className="code-list">
          <summary>All item codes ({items.length})</summary>
          <ul>
            {items.map((item) => (
              <li key={item.code}>
                <button type="button" className="code-row" onClick={() => void openItem(item)}>
                  <span className="item-code small-code">{item.code}</span>
                  <span>{item.name}</span>
                  <span className="muted small">Resin {item.resin.number}</span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
