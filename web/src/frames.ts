import { scaleToMaxSide, type Size } from "./geometry";

export interface Frame extends Size {
  blob: Blob;
}

function canvasToBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("encode"))), "image/jpeg", quality),
  );
}

/** Grab the current video frame as a JPEG, downscaled to keep uploads small. */
export async function captureVideoFrame(video: HTMLVideoElement, maxSide: number, quality: number): Promise<Frame> {
  const size = scaleToMaxSide({ width: video.videoWidth, height: video.videoHeight }, maxSide);
  if (!size.width || !size.height) throw new Error("no_frame");
  const canvas = document.createElement("canvas");
  canvas.width = size.width;
  canvas.height = size.height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("canvas");
  context.drawImage(video, 0, 0, size.width, size.height);
  return { blob: await canvasToBlob(canvas, quality), ...size };
}

/**
 * Decode a chosen file in the browser, apply its EXIF orientation and re-encode as JPEG.
 * This drops metadata such as GPS before upload and handles any format the browser can decode.
 */
export async function normaliseUpload(file: File, maxSide: number): Promise<Frame> {
  if (file.size > 40 * 1024 * 1024) throw new Error("too_large");
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new Error("undecodable");
  }
  const size = scaleToMaxSide({ width: bitmap.width, height: bitmap.height }, maxSide);
  const canvas = document.createElement("canvas");
  canvas.width = size.width;
  canvas.height = size.height;
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, size.width, size.height);
  bitmap.close();
  return { blob: await canvasToBlob(canvas, 0.88), ...size };
}

/**
 * Cut the selected box out of the photo, with generous context around it, as a base64 JPEG
 * (no data: prefix), and outline the box in green. The detector's box often covers only part of
 * an item (one hinge of a pair of glasses), so Gemini needs to see the whole object to name it.
 */
export async function cropToBase64(
  photo: Blob,
  box: { x1: number; y1: number; x2: number; y2: number },
  maxSide = 640,
  margin = 1,
): Promise<string> {
  const bitmap = await createImageBitmap(photo);
  const { width: w, height: h } = bitmap;
  const bw = (box.x2 - box.x1) * w;
  const bh = (box.y2 - box.y1) * h;
  let left = Math.max(0, box.x1 * w - bw * margin);
  let top = Math.max(0, box.y1 * h - bh * margin);
  let right = Math.min(w, box.x2 * w + bw * margin);
  let bottom = Math.min(h, box.y2 * h + bh * margin);
  // Small or thin boxes still need enough context to recognise: at least half the photo's short side.
  const minSide = Math.min(Math.max(160, Math.min(w, h) * 0.5), w, h);
  if (right - left < minSide) {
    const centre = (left + right) / 2;
    left = Math.max(0, Math.min(w - minSide, centre - minSide / 2));
    right = left + minSide;
  }
  if (bottom - top < minSide) {
    const centre = (top + bottom) / 2;
    top = Math.max(0, Math.min(h - minSide, centre - minSide / 2));
    bottom = top + minSide;
  }
  const size = scaleToMaxSide({ width: right - left, height: bottom - top }, maxSide);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(size.width));
  canvas.height = Math.max(1, Math.round(size.height));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("canvas");
  context.drawImage(bitmap, left, top, right - left, bottom - top, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  // Outline the selected box so Gemini knows which item is meant.
  const sx = canvas.width / (right - left);
  const sy = canvas.height / (bottom - top);
  context.strokeStyle = "#39ff14";
  context.lineWidth = Math.max(2, Math.round(canvas.width / 160));
  context.strokeRect((box.x1 * w - left) * sx, (box.y1 * h - top) * sy, bw * sx, bh * sy);
  const blob = await canvasToBlob(canvas, 0.85);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** The whole photo as base64 JPEG (no data: prefix), for feedback the user agreed to share. */
export async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
