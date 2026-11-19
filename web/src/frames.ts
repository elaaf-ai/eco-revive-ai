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
