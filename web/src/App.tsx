import { useCallback, useEffect, useRef, useState } from "react";
import { fetchReadiness } from "./api";
import { Home } from "./screens/Home";
import { Scanner } from "./screens/Scanner";
import type { Readiness, WasteClass } from "./types";

type Route = "home" | "scan";

const routeFromHash = (): Route => (window.location.hash === "#/scan" ? "scan" : "home");
const isRouteHash = (hash: string) => hash === "" || hash === "#" || hash.startsWith("#/");

function ModelStatus({ readiness }: { readiness: Readiness | null }) {
  if (!readiness) return <span className="model-status">Checking model…</span>;
  if (!readiness.ready || !readiness.model) {
    return <span className="model-status is-down">Model offline</span>;
  }
  const preview = readiness.model.status === "preview";
  return (
    <span className={`model-status${preview ? " is-preview" : ""}`}>
      Model {readiness.model.version}
      {preview ? " · preview, accuracy not yet verified" : ""}
    </span>
  );
}

export function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);
  const [message, setMessage] = useState("");
  const [readiness, setReadiness] = useState<Readiness | null>(null);

  useEffect(() => {
    const onHash = () => {
      if (isRouteHash(window.location.hash)) setRoute(routeFromHash());
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    const check = async () => {
      const result = await fetchReadiness(controller.signal);
      if (controller.signal.aborted) return;
      setReadiness(result);
      if (!result.ready) {
        attempt += 1;
        timer = setTimeout(() => void check(), Math.min(30_000, 2_000 * 2 ** Math.min(attempt, 4)));
      }
    };
    void check();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);

  // Move focus to the new screen on navigation, but not on first load, so the skip link stays first.
  const firstRoute = useRef(true);
  useEffect(() => {
    document.title = route === "scan" ? "Scan · EcoRevive" : "EcoRevive";
    if (firstRoute.current) {
      firstRoute.current = false;
      return;
    }
    document.getElementById("main")?.focus({ preventScroll: true });
  }, [route]);

  // The server decides which classes the product shows; Plastic is the default product.
  const enabled: WasteClass[] = readiness?.model?.enabled_classes?.length
    ? readiness.model.enabled_classes
    : ["Plastic"];

  const aiAvailable = readiness?.guide_provider === "gemini";

  // Re-setting identical text would not be re-announced, so clear first.
  const announce = useCallback((text: string) => {
    setMessage("");
    requestAnimationFrame(() => setMessage(text));
  }, []);

  return (
    <div className="app">
      <a
        className="skip"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <header className="topbar">
        <a href="#/" className="brand" aria-label="EcoRevive home">
          <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden>
            <rect width="32" height="32" rx="9" fill="var(--violet)" />
            <path d="M9 17.5c0-5.2 4.3-9 10.5-9.5-.4 6.6-4 10.6-9 10.6" fill="none" stroke="var(--lime)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M8.5 23.5c2-3.4 4.6-6 8-7.8" fill="none" stroke="var(--lime)" strokeWidth="2.6" strokeLinecap="round" />
          </svg>
          <span>EcoRevive</span>
        </a>
        <nav aria-label="Main">
          <a href="#/" aria-current={route === "home" ? "page" : undefined}>
            Home
          </a>
          <a href="#/scan" aria-current={route === "scan" ? "page" : undefined}>
            Scan
          </a>
        </nav>
      </header>

      <main id="main" tabIndex={-1}>
        {route === "home" ? (
          <Home
            onStart={() => (window.location.hash = "#/scan")}
            enabled={enabled}
            announce={announce}
            aiAvailable={aiAvailable}
          />
        ) : (
          <Scanner announce={announce} enabled={enabled} aiAvailable={aiAvailable} />
        )}
      </main>

      <footer className="footer">
        <ModelStatus readiness={readiness} />
        <span>Guides: {readiness?.guide_provider === "gemini" ? "Gemini with curated safety rules" : "curated"}</span>
      </footer>

      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {message}
      </div>
    </div>
  );
}
