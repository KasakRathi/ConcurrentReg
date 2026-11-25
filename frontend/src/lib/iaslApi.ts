import { API_BASE, ApiError } from "./api";
import type { IaslConfigView, IaslDecisions, IaslMetrics, IaslOff, IaslStatus } from "./iaslTypes";

/**
 * Client for the read-only IASL endpoints (app/iasl_api.py). Every response is shape-checked before use, so a wrong server or an
 * HTML error page is never shown as data, and every failure is a typed ApiError. When IASL is switched off the server still answers
 * 200 with {enabled:false}; that is returned as a normal value (IaslOff), not as an error.
 */

const STATES = new Set(["HEALTHY", "UNDER_PRESSURE", "OVERLOADED"]);

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const invalid = (what: string) => new ApiError("invalid", `The server answered, but not with the ${what} shape this dashboard expects. Is it an older or a different backend?`);

export const PREDATES_IASL_MESSAGE = "This backend has no /iasl endpoints (it predates IASL). Restart it from the current code.";

/** GET one /iasl path. Resolves to the parsed JSON; throws ApiError (unreachable | http | invalid). */
async function getJson(path: string, signal?: AbortSignal, timeoutMs = 4000): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const forward = () => controller.abort();
  signal?.addEventListener("abort", forward);
  try {
    const response = await fetch(`${API_BASE}${path}`, { signal: controller.signal, headers: { accept: "application/json" } });
    if (response.status === 404) throw new ApiError("http", PREDATES_IASL_MESSAGE, 404);
    if (!response.ok) throw new ApiError("http", `GET ${path} returned HTTP ${response.status}`, response.status);
    try {
      return await response.json();
    } catch {
      throw new ApiError("invalid", `GET ${path} did not return JSON.`);
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted) throw error; // the caller cancelled: let it see the abort
    throw new ApiError("unreachable", "The ConcurrentReg API did not answer. Is uvicorn running on port 8000?");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forward);
  }
}

function asOff(body: Record<string, unknown>, what: string): IaslOff {
  if (typeof body.message !== "string") throw invalid(what);
  return { enabled: false, message: body.message };
}

function isDecision(v: unknown): boolean {
  return isObj(v) && typeof v.id === "number" && typeof v.at_wall === "string" && typeof v.action === "string" &&
    typeof v.previous_state === "string" && typeof v.current_state === "string" && typeof v.rule === "string" &&
    typeof v.reason === "string" && typeof v.previous_value === "number" && typeof v.new_value === "number";
}

export function parseIaslStatus(body: unknown): IaslOff | IaslStatus {
  if (!isObj(body) || typeof body.enabled !== "boolean") throw invalid("/iasl/status");
  if (!body.enabled) return asOff(body, "/iasl/status");
  const stateOk = body.state === null || (typeof body.state === "string" && STATES.has(body.state));
  if (
    typeof body.attached !== "boolean" || typeof body.running !== "boolean" || !stateOk || typeof body.state_reason !== "string" ||
    !isObj(body.admission) || !isObj(body.fallback) || !isObj(body.loop) || typeof body.loop.ticks !== "number" ||
    typeof body.calibration !== "string" || (body.last_decision !== null && !isDecision(body.last_decision)) ||
    (body.last_control_action !== null && !isDecision(body.last_control_action)) || (body.current_metrics !== null && !isObj(body.current_metrics))
  ) throw invalid("/iasl/status");
  return body as unknown as IaslStatus;
}

export function parseIaslMetrics(body: unknown): IaslOff | IaslMetrics {
  if (!isObj(body) || typeof body.enabled !== "boolean") throw invalid("/iasl/metrics");
  if (!body.enabled) return asOff(body, "/iasl/metrics");
  const sampleOk = body.sample === null || (isObj(body.sample) && isObj(body.sample.gauges) && typeof body.sample.wall_time === "string");
  const analysisOk = body.analysis === null || (isObj(body.analysis) && Array.isArray(body.analysis.signals) && typeof body.analysis.state === "string");
  const historyOk = body.history === undefined || (Array.isArray(body.history) && body.history.every((r) => isObj(r) && typeof r.wall_time === "string"));
  if (!sampleOk || !analysisOk || !historyOk || typeof body.sampling_interval_s !== "number") throw invalid("/iasl/metrics");
  return body as unknown as IaslMetrics;
}

export function parseIaslDecisions(body: unknown): IaslOff | IaslDecisions {
  if (!isObj(body) || typeof body.enabled !== "boolean") throw invalid("/iasl/decisions");
  if (!body.enabled) return asOff(body, "/iasl/decisions");
  if (!Array.isArray(body.decisions) || !body.decisions.every(isDecision) || typeof body.kept !== "number") throw invalid("/iasl/decisions");
  return body as unknown as IaslDecisions;
}

export function parseIaslConfig(body: unknown): IaslConfigView {
  if (!isObj(body) || typeof body.enabled !== "boolean" || typeof body.active !== "boolean" || typeof body.read_only !== "boolean" ||
    !isObj(body.settings) || !isObj(body.environment_variables)) throw invalid("/iasl/config");
  return body as unknown as IaslConfigView;
}

export const fetchIaslStatus = async (signal?: AbortSignal, timeoutMs?: number) => parseIaslStatus(await getJson("/iasl/status", signal, timeoutMs));

/** `history` = how many recent samples to include (the server allows 0 to 120). */
export const fetchIaslMetrics = async (history = 0, signal?: AbortSignal, timeoutMs?: number) =>
  parseIaslMetrics(await getJson(`/iasl/metrics${history > 0 ? `?history=${Math.min(120, Math.floor(history))}` : ""}`, signal, timeoutMs));

/** `limit` = how many recent decisions (the server allows 1 to 200). */
export const fetchIaslDecisions = async (limit = 50, signal?: AbortSignal, timeoutMs?: number) =>
  parseIaslDecisions(await getJson(`/iasl/decisions?limit=${Math.max(1, Math.min(200, Math.floor(limit)))}`, signal, timeoutMs));

export const fetchIaslConfig = async (signal?: AbortSignal, timeoutMs?: number) => parseIaslConfig(await getJson("/iasl/config", signal, timeoutMs));
