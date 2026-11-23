import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { CLASS_META, percent } from "../classes";
import { boxToPercent, fitContain, labelPlacement, type Size } from "../geometry";
import type { Detection } from "../types";

interface StageProps {
  media: Size | null;
  detections: Detection[];
  selectedId: number | null;
  onSelect?: (id: number) => void;
  videoRef?: RefObject<HTMLVideoElement | null>;
  imageUrl?: string | null;
  showVideo: boolean;
  dimmed?: boolean;
  /** The Gemini vision check confirmed plastic in this photo. */
  aiConfirmed?: boolean;
  children?: ReactNode;
}

/** Shows the camera or captured image with detection boxes aligned to the same frame. */
export function Stage({
  media,
  detections,
  selectedId,
  onSelect,
  videoRef,
  imageUrl,
  showVideo,
  dimmed,
  aiConfirmed = false,
  children,
}: StageProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [container, setContainer] = useState<Size>({ width: 0, height: 0 });

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setContainer({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const frame = media ? fitContain(container, media) : null;

  return (
    <div
      className={`stage${media ? " has-media" : ""}`}
      ref={containerRef}
      style={media ? { ["--media-ratio" as string]: `${media.width} / ${media.height}` } : undefined}
    >
      <div
        className={`stage-frame${dimmed ? " is-dimmed" : ""}`}
        style={frame && frame.width ? { width: frame.width, height: frame.height } : { width: "100%", height: "100%" }}
      >
        {videoRef && (
          <video ref={videoRef} className="stage-media" playsInline muted hidden={!showVideo} aria-label="Camera preview" />
        )}
        {!showVideo && imageUrl && <img className="stage-media" src={imageUrl} alt="Captured photo being scanned" />}
        {media &&
          detections.map((detection) => {
            const meta = CLASS_META[detection.class_name];
            const selected = detection.id === selectedId;
            const label = aiConfirmed
              ? `${detection.class_name} ✓ AI-checked`
              : `${detection.class_name} ${percent(detection.confidence)}`;
            // In busy scenes, only label the selected and confident boxes so labels don't pile up.
            const showLabel = selected || detections.length <= 3 || detection.confidence >= 0.5 || aiConfirmed;
            return (
              <button
                key={detection.id}
                type="button"
                className={`box${selected ? " is-selected" : ""}`}
                style={{ ...boxToPercent(detection.box), ["--box-color" as string]: meta.color }}
                onClick={onSelect ? () => onSelect(detection.id) : undefined}
                tabIndex={onSelect ? 0 : -1}
                aria-pressed={onSelect ? selected : undefined}
                aria-label={onSelect ? `Select ${label}` : label}
                disabled={!onSelect}
              >
                {showLabel && (
                  <span className={`box-label is-${labelPlacement(detection.box)}`} aria-hidden>
                    {label}
                  </span>
                )}
              </button>
            );
          })}
      </div>
      {children}
    </div>
  );
}
