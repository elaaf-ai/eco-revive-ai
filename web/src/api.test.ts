import { afterEach, vi } from "vitest";
import { ApiError, detect, fetchGuide } from "./api";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

const busy = () => json(503, { error: { code: "overloaded", message: "Busy", retry_after_s: 0.01 } }, { "Retry-After": "1" });

afterEach(() => vi.restoreAllMocks());

it("sends raw image bytes with client id and idempotency key", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(json(200, { detections: [] }));
  await detect(new Blob(["x"], { type: "image/jpeg" }), { idempotencyKey: "key-12345678" });
  const [url, init] = fetchMock.mock.calls[0]!;
  const headers = new Headers(init?.headers);
  expect(url).toBe("/v1/detect");
  expect(headers.get("Content-Type")).toBe("image/jpeg");
  expect(headers.get("Idempotency-Key")).toBe("key-12345678");
  expect(headers.get("X-Client-Id")).toBeTruthy();
});

it("retries a busy response once with the same idempotency key", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(busy()).mockResolvedValueOnce(json(200, { ok: 1 }));
  await detect(new Blob(["x"]), { idempotencyKey: "key-abcdefgh", retries: 1 });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  const keys = fetchMock.mock.calls.map(([, init]) => new Headers(init?.headers).get("Idempotency-Key"));
  expect(keys).toEqual(["key-abcdefgh", "key-abcdefgh"]);
});

it("never retries without an idempotency key", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(busy());
  await expect(detect(new Blob(["x"]), { retries: 3 })).rejects.toMatchObject({ code: "overloaded", isBusy: true });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("maps the error envelope to ApiError", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    json(409, { error: { code: "confirmation_required", message: "Confirm it", request_id: "r" } }),
  );
  const error = await fetchGuide({ class_name: "Plastic", confidence: 0.2, confirmed_by_user: false }).catch((e) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error.code).toBe("confirmation_required");
});

it("reports network failures as retryable status 0", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
  await expect(detect(new Blob(["x"]), {})).rejects.toMatchObject({ status: 0, code: "network" });
});

it("aborts when the caller cancels, without retrying", async () => {
  const controller = new AbortController();
  vi.spyOn(globalThis, "fetch").mockImplementation(
    (_url, init) =>
      new Promise((_, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("x", "AbortError")))),
  );
  const pending = detect(new Blob(["x"]), { signal: controller.signal, idempotencyKey: "key-zzzzzzzz", retries: 2 });
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
});
