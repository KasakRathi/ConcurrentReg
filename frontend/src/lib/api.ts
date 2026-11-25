import type { OsLayerStatus } from "./types";

/**
 * Base URL of the FastAPI server as the browser sees it.
 * Default "/api": in development Vite proxies it to the backend (see vite.config.ts), so there is no CORS.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";

export type ApiErrorKind = "unreachable" | "http" | "invalid";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status?: number;
  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Cheap structural check so a wrong server (or an HTML error page) is never shown as metrics. */
export function parseOsLayerStatus(body: unknown): OsLayerStatus {
  if (
    !isRecord(body) ||
    !isRecord(body.queue) ||
    !isRecord(body.workers) ||
    !isRecord(body.db_semaphore) ||
    !isRecord(body.config) ||
    !isRecord(body.queue_wait) ||
    typeof body.queue.depth !== "number" ||
    typeof body.workers.active !== "number" ||
    typeof body.db_semaphore.permits !== "number"
  ) {
    throw new ApiError("invalid", "The server answered, but not with the /os-layer/status shape this dashboard expects.");
  }
  return body as unknown as OsLayerStatus;
}

export async function fetchOsLayerStatus(signal?: AbortSignal, timeoutMs = 4000): Promise<OsLayerStatus> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const forward = () => controller.abort();
  signal?.addEventListener("abort", forward);
  try {
    const response = await fetch(`${API_BASE}/os-layer/status`, { signal: controller.signal, headers: { accept: "application/json" } });
    if (!response.ok) {
      throw new ApiError("http", `GET /os-layer/status returned HTTP ${response.status}`, response.status);
    }
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new ApiError("invalid", "GET /os-layer/status did not return JSON.");
    }
    return parseOsLayerStatus(body);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted) throw error;
    throw new ApiError("unreachable", "The ConcurrentReg API did not answer. Is uvicorn running on port 8000?");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forward);
  }
}

/** True when the API did not answer, or answered 5xx. Behind the dev proxy a stopped backend shows up as HTTP 502/500. */
export const looksOffline = (e: ApiError) => e.kind === "unreachable" || (e.kind === "http" && (e.status ?? 0) >= 500);
