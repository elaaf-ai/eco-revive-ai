import { useCallback, useEffect, useRef, useState } from "react";

export type CameraStatus = "off" | "starting" | "live" | "denied" | "unavailable" | "insecure" | "busy" | "error";

const MESSAGES: Record<Exclude<CameraStatus, "off" | "starting" | "live">, string> = {
  denied: "Camera access was blocked. Allow it in your browser's site settings, or upload a photo instead.",
  unavailable: "No camera was found on this device. Upload a photo instead.",
  insecure: "The camera needs a secure (HTTPS) connection. Upload a photo instead.",
  busy: "Another app is using the camera. Close it and try again, or upload a photo.",
  error: "The camera could not start. Try again or upload a photo.",
};

export function cameraMessage(status: CameraStatus): string | null {
  return status in MESSAGES ? MESSAGES[status as keyof typeof MESSAGES] : null;
}

/** Owns one MediaStream. Tracks always stop on stop(), unmount, or when the tab is hidden. */
export function useCamera() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [status, setStatus] = useState<CameraStatus>("off");
  const [facing, setFacing] = useState<"environment" | "user">("environment");

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setStatus((current) => (current === "live" || current === "starting" ? "off" : current));
  }, []);

  const start = useCallback(
    async (mode: "environment" | "user" = facing) => {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setStatus("insecure");
        return;
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
      setStatus("starting");
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: mode }, width: { ideal: 1280 }, height: { ideal: 720 } },
        });
        streamRef.current = stream;
        setFacing(mode);
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => undefined);
        }
        setStatus("live");
      } catch (error) {
        const name = error instanceof DOMException ? error.name : "";
        setStatus(
          name === "NotAllowedError" || name === "SecurityError"
            ? "denied"
            : name === "NotFoundError" || name === "OverconstrainedError"
              ? "unavailable"
              : name === "NotReadableError" || name === "AbortError"
                ? "busy"
                : "error",
        );
      }
    },
    [facing],
  );

  useEffect(() => {
    const onHidden = () => {
      if (document.hidden) stop();
    };
    document.addEventListener("visibilitychange", onHidden);
    return () => {
      document.removeEventListener("visibilitychange", onHidden);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, [stop]);

  return { videoRef, status, facing, start, stop };
}
