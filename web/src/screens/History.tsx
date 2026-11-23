import { Camera, History as HistoryIcon, LoaderCircle, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, clearHistory, fetchHistory } from "../api";
import type { HistoryResponse, QualityStatus, SavedScan } from "../types";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; data: HistoryResponse };

const QUALITY_LABEL: Record<QualityStatus, string> = {
  ok: "Clear result",
  low_confidence: "Not sure",
  ambiguous: "Unclear material",
  no_detections: "Nothing found",
};

const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : formatter.format(date);
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function ScanRow({ scan }: { scan: SavedScan }) {
  const summary =
    scan.item_count === 0
      ? "No plastic found"
      : `${plural(scan.item_count, "plastic item")}, best ${Math.round((scan.top_confidence ?? 0) * 100)}%`;
  return (
    <li className="history-row">
      <span className="item-code small-code" aria-hidden>
        {scan.item_count}
      </span>
      <div className="history-main">
        <strong>{summary}</strong>
        <span className="muted small">
          <time dateTime={scan.created_at}>{formatWhen(scan.created_at)}</time> · {QUALITY_LABEL[scan.quality]}
        </span>
      </div>
      <span className="muted small history-model">Model {scan.model_version}</span>
    </li>
  );
}

export function History({ announce, enabled }: { announce: (message: string) => void; enabled: boolean }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [confirming, setConfirming] = useState(false);
  const [clearing, setClearing] = useState(false);

  const settle = (promise: Promise<HistoryResponse>, signal?: AbortSignal) =>
    promise
      .then((data) => setState({ status: "done", data }))
      .catch((error: unknown) => {
        if (signal?.aborted) return;
        setState({ status: "error", message: error instanceof ApiError ? error.message : "Could not load your history." });
      });

  const load = async () => {
    setState({ status: "loading" });
    await settle(fetchHistory());
  };

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    fetchHistory(controller.signal)
      .then((data) => setState({ status: "done", data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: error instanceof ApiError ? error.message : "Could not load your history." });
      });
    return () => controller.abort();
  }, [enabled]);

  const clear = async () => {
    setClearing(true);
    try {
      const { deleted } = await clearHistory();
      announce(`Deleted ${plural(deleted, "saved scan")}.`);
      setConfirming(false);
      await load();
    } catch (error) {
      announce(error instanceof ApiError ? error.message : "Could not delete your history.");
    } finally {
      setClearing(false);
    }
  };

  if (!enabled) {
    return (
      <div className="history">
        <h1 className="history-title">Scan history</h1>
        <p className="notice notice-warn">Scan history is not set up on this server. Scanning still works.</p>
      </div>
    );
  }

  return (
    <div className="history">
      <header className="history-head">
        <div>
          <h1 className="history-title">Your scan history</h1>
          <p className="muted">
            Scans you capture or upload are saved for this browser only. Photos are never stored.
          </p>
        </div>
      </header>

      {state.status === "loading" && (
        <p className="loading" role="status">
          <LoaderCircle size={18} className="spin" aria-hidden /> Loading your scans…
        </p>
      )}

      {state.status === "error" && (
        <div className="history-error">
          <p className="notice notice-error">{state.message}</p>
          <button type="button" className="btn btn-ghost" onClick={() => void load()}>
            Try again
          </button>
        </div>
      )}

      {state.status === "done" && (
        <>
          <section className="stats" aria-label="Totals">
            <div className="stat">
              <span className="stat-value">{state.data.you.scans}</span>
              <span className="stat-label">Scans saved</span>
            </div>
            <div className="stat">
              <span className="stat-value">{state.data.you.items_found}</span>
              <span className="stat-label">Plastic items found</span>
            </div>
            <div className="stat">
              <span className="stat-value">{state.data.you.items_this_week ?? 0}</span>
              <span className="stat-label">Found this week</span>
            </div>
            <div className="stat stat-everyone">
              <span className="stat-value">{state.data.everyone.items_found}</span>
              <span className="stat-label">Found by everyone using EcoRevive</span>
            </div>
          </section>

          {state.data.scans.length === 0 ? (
            <div className="panel-empty history-empty">
              <HistoryIcon size={28} aria-hidden />
              <h2>No saved scans yet</h2>
              <p className="muted">Take or upload a photo on the Scan screen and it will appear here.</p>
              <a className="btn btn-primary" href="#/scan">
                <Camera size={18} aria-hidden /> Start a scan
              </a>
            </div>
          ) : (
            <section aria-labelledby="recent-title" className="history-list">
              <h2 id="recent-title" className="section-title">
                Recent scans
              </h2>
              <ul>
                {state.data.scans.map((scan) => (
                  <ScanRow key={scan.id} scan={scan} />
                ))}
              </ul>
              <div className="history-clear">
                {confirming ? (
                  <>
                    <span>Delete all {plural(state.data.you.scans, "saved scan")} from this browser?</span>
                    <button type="button" className="btn btn-danger" disabled={clearing} onClick={() => void clear()}>
                      <Trash2 size={16} aria-hidden /> {clearing ? "Deleting…" : "Delete"}
                    </button>
                    <button type="button" className="btn btn-ghost" disabled={clearing} onClick={() => setConfirming(false)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
                    <Trash2 size={16} aria-hidden /> Clear history
                  </button>
                )}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
