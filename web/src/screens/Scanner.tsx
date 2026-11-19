import { Camera, ImageUp, Loader2, Radio, RefreshCw, SwitchCamera } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, detect, newIdempotencyKey } from "../api";
import { percent } from "../classes";
import { ResultsPanel } from "../components/ResultsPanel";
import { Stage } from "../components/Stage";
import { captureVideoFrame, normaliseUpload, type Frame } from "../frames";
import type { Size } from "../geometry";
import type { DetectResponse } from "../types";
import { cameraMessage, useCamera } from "../useCamera";

const LIVE_MIN_INTERVAL_MS = 900;
const LIVE_MAX_INTERVAL_MS = 6000;

type ScanState =
  | { status: "idle" }
  | { status: "scanning"; startedAt: number }
  | { status: "done"; result: DetectResponse }
  | { status: "error"; message: string; retry: boolean };

function prefersCaptureOnly(): boolean {
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } })
    .connection;
  return Boolean(connection?.saveData || ["slow-2g", "2g", "3g"].includes(connection?.effectiveType ?? ""));
}

function describe(result: DetectResponse): string {
  if (!result.detections.length) return "No waste item recognised.";
  const items = result.detections.map((d) => `${d.class_name} ${percent(d.confidence)}`).join(", ");
  return `Found ${result.detections.length}: ${items}.`;
}

export function Scanner({ announce }: { announce: (message: string) => void }) {
  const camera = useCamera();
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [frame, setFrame] = useState<(Frame & { url: string }) | null>(null);
  const [videoSize, setVideoSize] = useState<Size | null>(null);
  const [scan, setScan] = useState<ScanState>({ status: "idle" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [liveEnabled, setLiveEnabled] = useState(() => !prefersCaptureOnly());
  const [live, setLive] = useState<DetectResponse | null>(null);
  const [liveNotice, setLiveNotice] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const scanAbort = useRef<AbortController | null>(null);
  const scanSeq = useRef(0);

  const showingCamera = !frame;
  const cameraLive = camera.status === "live";

  // Release the captured image URL when it is replaced or the screen closes.
  useEffect(() => () => (frame ? URL.revokeObjectURL(frame.url) : undefined), [frame]);
  useEffect(() => () => scanAbort.current?.abort(), []);

  useEffect(() => {
    const video = camera.videoRef.current;
    if (!video) return;
    const update = () => video.videoWidth && setVideoSize({ width: video.videoWidth, height: video.videoHeight });
    video.addEventListener("loadedmetadata", update);
    video.addEventListener("resize", update);
    return () => {
      video.removeEventListener("loadedmetadata", update);
      video.removeEventListener("resize", update);
    };
  }, [camera.videoRef]);

  useEffect(() => {
    if (camera.status === "live") announce("Camera ready. Point it at one item.");
    const message = cameraMessage(camera.status);
    if (message) announce(message);
  }, [camera.status, announce]);

  // Live preview: one request in flight at a time, adaptive interval, stale results dropped.
  useEffect(() => {
    if (!liveEnabled || !cameraLive || !showingCamera) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inflight: AbortController | null = null;
    let interval = LIVE_MIN_INTERVAL_MS;

    const schedule = (ms: number) => {
      if (!cancelled) timer = setTimeout(tick, ms);
    };
    const tick = async () => {
      const video = camera.videoRef.current;
      if (cancelled || !video || document.hidden || !video.videoWidth) return schedule(1000);
      const started = performance.now();
      inflight = new AbortController();
      try {
        const sample = await captureVideoFrame(video, 640, 0.7);
        const result = await detect(sample.blob, { signal: inflight.signal, timeoutMs: 8000, retries: 0 });
        if (cancelled) return;
        setLive(result);
        setLiveNotice(null);
        interval = Math.max(LIVE_MIN_INTERVAL_MS, interval * 0.8);
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && (error.isBusy || error.status === 0)) {
          interval = Math.min(LIVE_MAX_INTERVAL_MS, interval * 2);
          setLiveNotice(error.status === 0 ? "Slow connection. Live preview is paused; use Capture." : "Server busy. Live preview slowed down.");
        } else if (error instanceof ApiError && error.code === "model_unavailable") {
          setLiveNotice("The model is offline right now.");
          interval = LIVE_MAX_INTERVAL_MS;
        }
      }
      schedule(Math.max(interval, performance.now() - started));
    };
    schedule(300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      inflight?.abort();
      setLive(null);
    };
  }, [liveEnabled, cameraLive, showingCamera, camera.videoRef]);

  useEffect(() => {
    if (scan.status !== "scanning") return;
    const timer = setInterval(() => setElapsed(Math.round((performance.now() - scan.startedAt) / 1000)), 500);
    return () => clearInterval(timer);
  }, [scan]);

  const runScan = useCallback(
    async (image: Frame) => {
      scanAbort.current?.abort();
      const controller = new AbortController();
      scanAbort.current = controller;
      const seq = ++scanSeq.current;
      setSelectedId(null);
      setElapsed(0);
      setScan({ status: "scanning", startedAt: performance.now() });
      announce("Scanning the photo…");
      try {
        const result = await detect(image.blob, {
          signal: controller.signal,
          timeoutMs: 20000,
          idempotencyKey: newIdempotencyKey(),
          retries: 1,
        });
        if (seq !== scanSeq.current) return;
        setScan({ status: "done", result });
        if (result.detections.length === 1) setSelectedId(result.detections[0]?.id ?? null);
        announce(describe(result));
      } catch (error) {
        if (controller.signal.aborted || seq !== scanSeq.current) return;
        const message = error instanceof ApiError ? error.message : "The scan failed. Try again.";
        setScan({ status: "error", message, retry: !(error instanceof ApiError) || error.status === 0 || error.isBusy || error.status >= 500 });
        announce(message);
      }
    },
    [announce],
  );

  const showImage = (image: Frame) => {
    setFrame({ ...image, url: URL.createObjectURL(image.blob) });
    camera.stop();
    void runScan(image);
  };

  const capture = async () => {
    const video = camera.videoRef.current;
    if (!video) return;
    try {
      showImage(await captureVideoFrame(video, 1280, 0.9));
    } catch {
      announce("Could not capture a frame. Try again.");
    }
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      showImage(await normaliseUpload(file, 1280));
    } catch (error) {
      const tooLarge = error instanceof Error && error.message === "too_large";
      const message = tooLarge ? "That file is too large. Choose a photo under 40 MB." : "That file isn't an image this browser can open.";
      setScan({ status: "error", message, retry: false });
      announce(message);
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const retake = () => {
    scanAbort.current?.abort();
    scanSeq.current++;
    setFrame(null);
    setScan({ status: "idle" });
    setSelectedId(null);
    void camera.start();
  };

  const cameraError = cameraMessage(camera.status);
  const stageDetections = showingCamera ? (live?.detections ?? []) : scan.status === "done" ? scan.result.detections : [];

  return (
    <div className="scanner">
      <section className="scanner-stage" aria-label="Scanner">
        <Stage
          media={showingCamera ? videoSize : frame}
          detections={stageDetections}
          selectedId={showingCamera ? null : selectedId}
          onSelect={showingCamera ? undefined : setSelectedId}
          videoRef={camera.videoRef}
          imageUrl={frame?.url}
          showVideo={showingCamera && cameraLive}
          dimmed={scan.status === "scanning"}
        >
          {showingCamera && !cameraLive && (
            <div className="stage-placeholder">
              {camera.status === "starting" ? (
                <p className="loading" role="status">
                  <Loader2 className="spin" size={18} aria-hidden /> Starting camera…
                </p>
              ) : (
                <>
                  <Camera size={36} aria-hidden />
                  <p>{cameraError ?? "Use your camera or upload a photo of one waste item."}</p>
                  {camera.status !== "insecure" && camera.status !== "unavailable" && (
                    <button type="button" className="btn btn-primary" onClick={() => void camera.start()}>
                      <Camera size={18} aria-hidden /> {camera.status === "off" ? "Start camera" : "Try camera again"}
                    </button>
                  )}
                </>
              )}
            </div>
          )}
          {scan.status === "scanning" && (
            <p className="stage-status" role="status">
              <Loader2 className="spin" size={18} aria-hidden />
              {elapsed >= 5 ? `Still scanning (${elapsed}s). The connection is slow.` : "Scanning…"}
            </p>
          )}
          {showingCamera && cameraLive && liveEnabled && (
            <p className="stage-chip" aria-hidden>
              <Radio size={14} /> {liveNotice ?? (live ? `Live · ${live.detections.length} seen` : "Live preview")}
            </p>
          )}
        </Stage>

        <div className="controls">
          <button type="button" className="btn btn-icon" onClick={() => fileInput.current?.click()} aria-label="Upload a photo">
            <ImageUp size={22} aria-hidden />
          </button>
          {showingCamera ? (
            <button
              type="button"
              className="shutter"
              onClick={() => void capture()}
              disabled={!cameraLive}
              aria-label="Capture and scan"
            >
              <span />
            </button>
          ) : (
            <button type="button" className="btn btn-primary btn-wide" onClick={retake}>
              <RefreshCw size={18} aria-hidden /> New scan
            </button>
          )}
          {showingCamera ? (
            <button
              type="button"
              className="btn btn-icon"
              onClick={() => void camera.start(camera.facing === "environment" ? "user" : "environment")}
              disabled={!cameraLive}
              aria-label="Switch camera"
            >
              <SwitchCamera size={22} aria-hidden />
            </button>
          ) : (
            <span className="btn-icon-spacer" />
          )}
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            hidden
            onChange={(event) => void onFile(event.target.files?.[0])}
          />
        </div>
        {showingCamera && (
          <label className="toggle">
            <input type="checkbox" checked={liveEnabled} onChange={(event) => setLiveEnabled(event.target.checked)} />
            <span>Live preview</span>
            <small>Turn off on slow phones or networks. Capture still works.</small>
          </label>
        )}
      </section>

      <section className="scanner-panel" aria-label="Results">
        {scan.status === "idle" && (
          <div className="panel-intro">
            <h2>How to scan</h2>
            <ol className="steps">
              <li>Place one item on a plain surface in good light.</li>
              <li>Fill most of the frame with it, then press the shutter.</li>
              <li>Pick the item to get a reuse idea or safe disposal steps.</li>
            </ol>
            <p className="muted">Photos are scanned and discarded. They are not stored.</p>
          </div>
        )}
        {scan.status === "scanning" && (
          <div className="panel-intro">
            <p className="loading">
              <Loader2 className="spin" size={18} aria-hidden /> Looking for waste items…
            </p>
          </div>
        )}
        {scan.status === "error" && (
          <div className="panel-empty">
            <h2>Scan didn't finish</h2>
            <p className="notice notice-error">{scan.message}</p>
            {scan.retry && frame && (
              <button type="button" className="btn btn-primary" onClick={() => void runScan(frame)}>
                <RefreshCw size={18} aria-hidden /> Try again
              </button>
            )}
            <button type="button" className="btn btn-ghost" onClick={retake}>
              New scan
            </button>
          </div>
        )}
        {scan.status === "done" && (
          <ResultsPanel
            key={scan.result.request_id}
            result={scan.result}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onRetake={retake}
            announce={announce}
          />
        )}
      </section>
    </div>
  );
}
