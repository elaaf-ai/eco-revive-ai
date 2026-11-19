import type { Box } from "./types";

export interface Size {
  width: number;
  height: number;
}

/** Largest size with the media's aspect ratio that fits inside the container. */
export function fitContain(container: Size, media: Size): Size {
  if (media.width <= 0 || media.height <= 0 || container.width <= 0 || container.height <= 0) {
    return { width: 0, height: 0 };
  }
  const scale = Math.min(container.width / media.width, container.height / media.height);
  return { width: Math.floor(media.width * scale), height: Math.floor(media.height * scale) };
}

/** Normalized box to CSS percentages of the frame that shows the whole image. */
export function boxToPercent(box: Box): { left: string; top: string; width: string; height: string } {
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  const x1 = clamp(box.x1);
  const y1 = clamp(box.y1);
  const x2 = clamp(box.x2);
  const y2 = clamp(box.y2);
  const pct = (v: number) => `${(v * 100).toFixed(3)}%`;
  return { left: pct(x1), top: pct(y1), width: pct(Math.max(0, x2 - x1)), height: pct(Math.max(0, y2 - y1)) };
}

/** Put the label above the box, or inside it when the box touches the top edge. */
export function labelPlacement(box: Box): "above" | "inside" {
  return box.y1 < 0.07 ? "inside" : "above";
}

/** Downscaled size keeping aspect ratio, never upscaling. */
export function scaleToMaxSide(size: Size, maxSide: number): Size {
  const longest = Math.max(size.width, size.height);
  if (longest <= maxSide) return { ...size };
  const scale = maxSide / longest;
  return { width: Math.round(size.width * scale), height: Math.round(size.height * scale) };
}
