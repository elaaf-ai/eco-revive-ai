import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { useCamera } from "./useCamera";

function fakeStream() {
  const track = { readyState: "live", stop: vi.fn(function (this: { readyState: string }) { this.readyState = "ended"; }) };
  return { getTracks: () => [track], track };
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event("visibilitychange"));
}

afterEach(() => {
  setHidden(false);
  vi.restoreAllMocks();
});

it("B-21: the camera stops when the tab is hidden and resumes when it is shown again", async () => {
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  const streams: ReturnType<typeof fakeStream>[] = [];
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => {
        const stream = fakeStream();
        streams.push(stream);
        return stream;
      }),
    },
  });

  const { result } = renderHook(() => useCamera());
  await act(async () => {
    await result.current.start();
  });
  expect(result.current.status).toBe("live");

  act(() => setHidden(true));
  expect(streams[0]!.track.stop).toHaveBeenCalled();
  expect(result.current.status).toBe("off");

  act(() => setHidden(false));
  await waitFor(() => expect(result.current.status).toBe("live"));
  expect(streams).toHaveLength(2);
});

it("B-21: a camera the user switched off stays off when the tab returns", async () => {
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  const getUserMedia = vi.fn(async () => fakeStream());
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });

  const { result } = renderHook(() => useCamera());
  act(() => setHidden(true));
  act(() => setHidden(false));
  expect(getUserMedia).not.toHaveBeenCalled();
  expect(result.current.status).toBe("off");
});
