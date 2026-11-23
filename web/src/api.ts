import type {
  CatalogItem,
  DetectResponse,
  GuideRequest,
  GuideResponse,
  HistoryResponse,
  ItemSummary,
  Readiness,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfterS?: number;

  constructor(status: number, code: string, message: string, retryAfterS?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfterS = retryAfterS;
  }

  get isBusy(): boolean {
    return this.code === "overloaded" || this.code === "rate_limited" || this.code === "inference_timeout";
  }
}

let memoryClientId: string | null = null;

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** Anonymous per-browser id. It scopes idempotency keys and this browser's scan history; the server stores only a hash. */
export function clientId(): string {
  try {
    const stored = localStorage.getItem("ecorevive-client-id");
    if (stored) return stored;
    const id = newId();
    localStorage.setItem("ecorevive-client-id", id);
    return id;
  } catch {
    memoryClientId ??= newId();
    return memoryClientId;
  }
}

export const newIdempotencyKey = newId;

interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs: number;
  idempotencyKey?: string;
  /** Retries for network errors and busy responses. Only safe with an idempotency key. */
  retries?: number;
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

async function request<T>(path: string, init: RequestInit, options: RequestOptions): Promise<T> {
  const attempts = 1 + (options.idempotencyKey ? (options.retries ?? 0) : 0);
  let lastError: unknown;
  for (let attempt = 0; attempt < attempts; attempt++) {
    const controller = new AbortController();
    const onAbort = () => controller.abort();
    options.signal?.addEventListener("abort", onAbort);
    const timer = setTimeout(() => controller.abort(new DOMException("Timeout", "TimeoutError")), options.timeoutMs);
    try {
      const headers = new Headers(init.headers);
      headers.set("X-Client-Id", clientId());
      if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey);
      const response = await fetch(`${BASE}${path}`, { ...init, headers, signal: controller.signal });
      if (response.ok) return (await response.json()) as T;
      throw await toApiError(response);
    } catch (error) {
      if (options.signal?.aborted) throw new DOMException("Aborted", "AbortError");
      lastError = normalise(error);
      const retryable = lastError instanceof ApiError && (lastError.status === 0 || lastError.isBusy);
      if (!retryable || attempt === attempts - 1) throw lastError;
      const waitS = Math.min((lastError as ApiError).retryAfterS ?? 1, 3);
      await sleep(waitS * 1000, options.signal);
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }
  }
  throw lastError;
}

async function toApiError(response: Response): Promise<ApiError> {
  const retryHeader = Number(response.headers.get("Retry-After"));
  try {
    const body = await response.json();
    const error = body?.error;
    if (error?.code) {
      return new ApiError(response.status, error.code, error.message, error.retry_after_s ?? (retryHeader || undefined));
    }
  } catch {
    // Non-JSON error, for example from a proxy.
  }
  return new ApiError(response.status, `http_${response.status}`, "The server returned an error.", retryHeader || undefined);
}

function normalise(error: unknown): unknown {
  if (error instanceof ApiError) return error;
  if (error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError")) {
    return new ApiError(0, "timeout", "The connection is slow. The request timed out.");
  }
  if (error instanceof TypeError) {
    return new ApiError(0, "network", "Can't reach EcoRevive. Check your connection.");
  }
  return error;
}

export function detect(
  image: Blob,
  options: {
    signal?: AbortSignal;
    timeoutMs?: number;
    idempotencyKey?: string;
    retries?: number;
    /** Save the result to this browser's history. */
    save?: boolean;
    /** Ask the server for the Gemini vision second opinion. Never for live preview frames. */
    verify?: boolean;
  },
): Promise<DetectResponse> {
  const params = new URLSearchParams();
  if (options.save) params.set("save", "true");
  if (options.verify) params.set("verify", "true");
  const query = params.toString();
  return request<DetectResponse>(
    query ? `/v1/detect?${query}` : "/v1/detect",
    { method: "POST", body: image, headers: { "Content-Type": image.type || "image/jpeg" } },
    { timeoutMs: options.timeoutMs ?? 15000, ...options },
  );
}

export function fetchGuide(body: GuideRequest, signal?: AbortSignal): Promise<GuideResponse> {
  return request<GuideResponse>(
    "/v1/guides",
    { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } },
    { signal, timeoutMs: 30000, idempotencyKey: newId(), retries: 1 },
  );
}

export async function fetchItems(signal?: AbortSignal): Promise<ItemSummary[]> {
  const body = await request<{ items?: ItemSummary[] }>("/v1/items", { method: "GET" }, { signal, timeoutMs: 15000 });
  return Array.isArray(body.items) ? body.items : [];
}

export function fetchItem(code: string, signal?: AbortSignal): Promise<CatalogItem> {
  return request<CatalogItem>(`/v1/items/${encodeURIComponent(code)}`, { method: "GET" }, { signal, timeoutMs: 15000 });
}

/** Find an item by code ("1", "001", "#1") or by name/alias. Exact code wins. */
export function matchItems(items: ItemSummary[], query: string): ItemSummary[] {
  const text = query.trim().replace(/^#/, "").toLowerCase();
  if (!text) return [];
  if (/^\d{1,3}$/.test(text)) {
    const code = text.padStart(3, "0");
    const exact = items.filter((item) => item.code === code);
    return exact.length ? exact : items.filter((item) => item.code.startsWith(text));
  }
  return items.filter(
    (item) => item.name.toLowerCase().includes(text) || item.aliases.some((alias) => alias.toLowerCase().includes(text)),
  );
}

export function fetchHistory(signal?: AbortSignal, limit = 20): Promise<HistoryResponse> {
  return request<HistoryResponse>(`/v1/history?limit=${limit}`, { method: "GET" }, { signal, timeoutMs: 15000 });
}

export function clearHistory(signal?: AbortSignal): Promise<{ deleted: number }> {
  return request<{ deleted: number }>("/v1/history", { method: "DELETE" }, { signal, timeoutMs: 15000 });
}

export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  try {
    const response = await fetch(`${BASE}/readyz`, { signal });
    return (await response.json()) as Readiness;
  } catch {
    return { ready: false, model_loaded: false, model: null, guide_provider: "curated_only", detail: "unreachable" };
  }
}
