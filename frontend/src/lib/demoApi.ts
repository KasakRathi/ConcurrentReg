import { API_BASE } from "./api";
import type { ExperimentResult } from "./types";

/**
 * Client for the demo controls (app/demo_api.py). Every response is shape-checked before use, and every failure
 * is a typed error, so the UI can show "controls are off" or "server busy" instead of stale or invented data.
 */
export type DemoErrorKind = "disabled" | "busy" | "invalid" | "refused" | "unreachable" | "http";

export class DemoError extends Error {
  kind: DemoErrorKind;
  status?: number;
  constructor(kind: DemoErrorKind, message: string, status?: number) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

export interface DemoInfo {
  controls_enabled: boolean;
  database: { dialect: string; version: string | null; name: string | null; row_locks: boolean };
  os_layer: { queue_capacity: number; worker_count: number; db_semaphore_permits: number };
  generator_version: string;
  generator_revision: string | null;
  tests: { available: boolean; reason: string | null; dialect: string | null };
  results_dir: string | null;
}

export interface Invariant {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
}

export interface SectionRow {
  id: number;
  course_code: string;
  course_name: string;
  capacity: number;
  available_seats: number;
  registered: number;
}

export interface DemoState {
  taken_at: string;
  database: DemoInfo["database"];
  sections: SectionRow[];
  totals: { students: number; registrations: number };
  invariants: Invariant[];
  all_ok: boolean;
}

export interface DbCheck {
  registrations_in_db: number;
  successes_reported_by_client: number;
  match: boolean | null;
  invariants_ok: boolean;
  note: string | null;
}

export interface RunJob {
  job_id: string;
  status: "running" | "done" | "failed" | "none";
  started_at: string;
  reset_first: boolean;
  config: Record<string, unknown>;
  progress: { planned_requests: number; responses_seen: number; fraction: number; elapsed_s: number; note: string };
  experiment_id: string | null;
  summary: {
    total_requests: number;
    successful_requests: number;
    category_counts: Record<string, number>;
    elapsed_seconds: number;
    completed_requests_per_second: number | null;
    latency_ms: { average: number; p50: number; p95: number; p99: number; min: number; max: number } | null;
    valid_open_loop: boolean | null;
  } | null;
  db_check: DbCheck | null;
  error: string | null;
}

export interface ServerResultItem {
  experiment_id: string;
  modified_at: string;
  size_bytes: number;
  arrival_model: string | null;
  pattern: string | null;
  contention: string | null;
  total_requests: number;
  successful_requests: number;
  has_server_context: boolean;
}

export interface RegistrationRow {
  id: number;
  student: string;
  course: string;
  registered_at: string;
  status: string;
}

export type TestStatus = "PASSED" | "FAILED" | "SKIPPED" | "ERROR" | "XFAIL" | "XPASS";

export interface LiveTest {
  file: string;
  name: string;
  status: TestStatus;
  reason: string;
  percent: number | null;
}

export interface VerifySnapshot {
  job_id?: string;
  status: "running" | "done" | "failed" | "none";
  started_at?: string;
  elapsed_s?: number;
  dialect?: string;
  percent?: number;
  live_counts?: { passed: number; failed: number; skipped: number; error: number };
  recent?: LiveTest[];
  report?: { counts: { total: number; passed: number; failed: number; skipped: number; error: number }; tests: Array<{ file: string; name: string; status: TestStatus; reason: string; time_s: number }> } | null;
  error?: string | null;
  output_tail?: string[];
}

/** The generator options the server accepts (a subset of WorkloadConfig). */
export interface RunRequest {
  arrival_model?: "open" | "closed";
  pattern?: "steady" | "burst" | "ramp" | "phases";
  request_count?: number;
  rate?: number;
  ramp_stages?: number;
  phases?: number[][];
  concurrency?: number;
  contention?: "hot" | "independent" | "mixed";
  section_ids?: number[] | null;
  hot_section_count?: number;
  hot_fraction?: number;
  duplicate_fraction?: number;
  student_count?: number;
  virtual_users?: number;
  think_time_min_s?: number;
  think_time_max_s?: number;
  seed?: number;
  timeout_seconds?: number;
  lateness_tolerance_ms?: number;
  reset_first?: boolean;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

async function call<T>(path: string, init?: RequestInit, timeoutMs = 15000): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal, headers: { accept: "application/json", ...(init?.body ? { "content-type": "application/json" } : {}) } });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* not JSON */
    }
    if (!response.ok) {
      const detail = isObj(body) && typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
      if (response.status === 404 && /Demo controls are disabled/.test(detail)) throw new DemoError("disabled", "The server's demo controls are off. Start it with CREG_DEMO_CONTROLS=1.", 404);
      if (response.status === 409) throw new DemoError("busy", detail, 409);
      if (response.status === 422) throw new DemoError("invalid", detail, 422);
      throw new DemoError("http", detail, response.status);
    }
    return body as T;
  } catch (error) {
    if (error instanceof DemoError) throw error;
    throw new DemoError("unreachable", "The ConcurrentReg API did not answer. Is uvicorn running?");
  } finally {
    clearTimeout(timer);
  }
}

export function parseInfo(body: unknown): DemoInfo {
  if (!isObj(body) || typeof body.controls_enabled !== "boolean" || !isObj(body.database) || !isObj(body.os_layer) || !isObj(body.tests)) {
    throw new DemoError("http", "The server answered, but not with the /demo/info shape this dashboard expects. Is it an older backend?");
  }
  return body as unknown as DemoInfo;
}

export function parseState(body: unknown): DemoState {
  if (!isObj(body) || !Array.isArray(body.sections) || !Array.isArray(body.invariants) || !isObj(body.totals) || typeof body.all_ok !== "boolean") {
    throw new DemoError("http", "Unexpected /demo/state response.");
  }
  return body as unknown as DemoState;
}

export function parseRun(body: unknown): RunJob {
  if (!isObj(body) || typeof body.status !== "string") throw new DemoError("http", "Unexpected run response.");
  return body as unknown as RunJob;
}

export const getInfo = async () => parseInfo(await call("/demo/info"));
export const getState = async () => parseState(await call("/demo/state"));
export const resetData = async () => parseState(await call("/demo/reset", { method: "POST" }, 60000));
export const startRun = async (body: RunRequest) => parseRun(await call("/demo/runs", { method: "POST", body: JSON.stringify(body) }, 60000));
export const getRun = async (id: string) => parseRun(await call(`/demo/runs/${encodeURIComponent(id)}`));
export const getCurrentRun = async () => parseRun(await call("/demo/runs/current"));
export const setServerSettings = async (s: DemoInfo["os_layer"]) => (await call("/demo/os-layer", { method: "POST", body: JSON.stringify(s) }, 60000)) as DemoInfo["os_layer"];
export const listServerResults = async () => ((await call("/demo/results")) as { folder: string; items: ServerResultItem[] });
export const getServerResult = async (id: string) => (await call(`/demo/results/${encodeURIComponent(id)}`, undefined, 60000)) as ExperimentResult;
export const getRegistrations = async () => ((await call("/demo/registrations")) as { items: RegistrationRow[] }).items;
export const startVerify = async () => (await call("/demo/verify", { method: "POST" }, 30000)) as VerifySnapshot;
export const getVerify = async () => (await call("/demo/verify/current")) as VerifySnapshot;

/** Map the dashboard's WorkloadConfig to what the server accepts. */
export function configToRunRequest(c: {
  arrival_model: "open" | "closed"; pattern: "steady" | "burst" | "ramp" | "phases"; request_count: number; rate: number; ramp_stages: number;
  phases: [number, number][]; concurrency: number; contention: "hot" | "independent" | "mixed"; section_ids: number[]; hot_section_count: number;
  hot_fraction: number; duplicate_fraction: number; student_count: number; virtual_users: number; think_time_min_s: number; think_time_max_s: number;
  seed: number; timeout_seconds: number; lateness_tolerance_ms: number;
}, resetFirst = true): RunRequest {
  return { ...c, phases: c.phases.map((p) => [...p]), reset_first: resetFirst };
}

/** Group a finished report by test file, for the "by file" summary. */
export function groupByFile(tests: NonNullable<VerifySnapshot["report"]>["tests"]) {
  const map = new Map<string, { file: string; passed: number; failed: number; skipped: number; error: number; total: number }>();
  for (const t of tests) {
    const row = map.get(t.file) ?? { file: t.file, passed: 0, failed: 0, skipped: 0, error: 0, total: 0 };
    row.total += 1;
    if (t.status === "PASSED") row.passed += 1;
    else if (t.status === "FAILED") row.failed += 1;
    else if (t.status === "SKIPPED") row.skipped += 1;
    else if (t.status === "ERROR") row.error += 1;
    map.set(t.file, row);
  }
  return [...map.values()].sort((a, b) => a.file.localeCompare(b.file));
}
