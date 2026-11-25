import { ALL_CATEGORIES, type Category, type ExperimentResult, type RequestRecord } from "./types";

// ---------------------------------------------------------------- parsing

export class ResultParseError extends Error {}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Accept a workload-generator result file. Only the fields this dashboard relies on are checked;
 * older files without the "run" block or the intended-arrival fields are still accepted.
 * Nothing is invented: a missing field stays missing and the UI shows "n/a".
 */
export function parseExperiment(text: string): ExperimentResult {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new ResultParseError("This file is not valid JSON.");
  }
  if (!isRecord(raw)) throw new ResultParseError("The JSON must be an object written by the workload generator.");
  if (typeof raw.experiment_id !== "string") throw new ResultParseError("Missing experiment_id: not a workload-generator result file.");
  if (!isRecord(raw.config)) throw new ResultParseError("Missing config block.");
  if (!isRecord(raw.summary) || !isRecord(raw.summary.category_counts)) throw new ResultParseError("Missing summary.category_counts.");
  if (!Array.isArray(raw.results)) throw new ResultParseError("Missing results array.");
  for (const row of raw.results) {
    if (!isRecord(row) || typeof row.request_id !== "string" || typeof row.category !== "string") {
      throw new ResultParseError("A results row has no request_id or category.");
    }
    if (!(ALL_CATEGORIES as string[]).includes(row.category)) {
      throw new ResultParseError(`Unknown result category "${row.category}". Is this file from a newer generator?`);
    }
  }
  return raw as unknown as ExperimentResult;
}

// ---------------------------------------------------------------- statistics

/** Nearest-rank percentile of an ascending list. Same rule as workload_generator.percentile(). */
export function percentile(sorted: number[], percent: number): number {
  const rank = Math.ceil((percent / 100) * sorted.length);
  return sorted[Math.max(rank, 1) - 1];
}

export function numbers(values: Array<number | null | undefined>): number[] {
  return values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
}

export interface PercentileRow {
  label: string;
  value: number;
}

export function percentileRows(values: number[]): PercentileRow[] {
  if (values.length === 0) return [];
  const sorted = [...values].sort((a, b) => a - b);
  return [
    { label: "min", value: sorted[0] },
    { label: "p50", value: percentile(sorted, 50) },
    { label: "p90", value: percentile(sorted, 90) },
    { label: "p95", value: percentile(sorted, 95) },
    { label: "p99", value: percentile(sorted, 99) },
    { label: "max", value: sorted[sorted.length - 1] },
  ];
}

// ---------------------------------------------------------------- time series

export interface RateBin {
  t: number; // bin start, seconds after the experiment started
  offered: number; // requests whose intended arrival falls in the bin (per second)
  dispatched: number; // requests actually sent in the bin (per second)
  completed: number; // responses (any outcome) received in the bin (per second)
  succeeded: number; // SUCCESS responses received in the bin (per second)
}

/** Count events per bin and convert to a per-second rate. Open-loop only for "offered". */
export function rateBins(results: RequestRecord[], binSeconds: number): RateBin[] {
  const sent = results.filter((r) => r.category !== "NOT_DISPATCHED");
  const ends = numbers(sent.map((r) => r.end_offset_s));
  const sends = numbers(sent.map((r) => r.sent_offset_s ?? r.start_offset_s));
  const intended = numbers(results.map((r) => r.intended_offset_s ?? r.planned_offset_s));
  const horizon = Math.max(0, ...ends, ...sends, ...intended);
  const count = Math.max(1, Math.ceil((horizon + 1e-9) / binSeconds));
  const bins: RateBin[] = Array.from({ length: count }, (_, i) => ({ t: i * binSeconds, offered: 0, dispatched: 0, completed: 0, succeeded: 0 }));
  const put = (time: number | null | undefined, key: keyof Omit<RateBin, "t">) => {
    if (time == null || !Number.isFinite(time)) return;
    const index = Math.min(count - 1, Math.max(0, Math.floor(time / binSeconds)));
    bins[index][key] += 1 / binSeconds;
  };
  for (const r of results) put(r.intended_offset_s ?? r.planned_offset_s, "offered");
  for (const r of sent) {
    put(r.sent_offset_s ?? r.start_offset_s, "dispatched");
    put(r.end_offset_s, "completed");
    if (r.category === "SUCCESS") put(r.end_offset_s, "succeeded");
  }
  return bins;
}

/** Pick a bin width that gives roughly 20 to 60 bars, from a short list of round numbers. */
export function chooseBinSeconds(results: RequestRecord[]): number {
  const ends = numbers(results.map((r) => r.end_offset_s));
  const span = Math.max(0.001, ...ends);
  const options = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60];
  return options.find((o) => span / o <= 60) ?? 60;
}

export interface HistogramBin {
  from: number;
  to: number;
  label: string;
  count: number;
}

/** Linear histogram from 0 to just above the p99, plus one "overflow" bin so outliers stay visible. */
export function latencyHistogram(values: number[], bins = 24): HistogramBin[] {
  if (values.length === 0) return [];
  const sorted = [...values].sort((a, b) => a - b);
  const top = Math.max(percentile(sorted, 99), sorted[0] + 1e-6);
  const width = top / bins;
  const out: HistogramBin[] = Array.from({ length: bins }, (_, i) => ({
    from: i * width,
    to: (i + 1) * width,
    label: `${(i * width).toFixed(width < 10 ? 1 : 0)}`,
    count: 0,
  }));
  let overflow = 0;
  for (const v of sorted) {
    if (v > top) overflow += 1;
    else out[Math.min(bins - 1, Math.floor(v / width))].count += 1;
  }
  if (overflow > 0) out.push({ from: top, to: sorted[sorted.length - 1], label: `>${top.toFixed(top < 10 ? 1 : 0)}`, count: overflow });
  return out;
}

export interface SeriesPoint {
  x: number;
  y: number;
}

/** Keep at most `limit` points by taking evenly spaced ones (keeps the first and last). */
export function downsample<T>(points: T[], limit: number): T[] {
  if (points.length <= limit) return points;
  const step = (points.length - 1) / (limit - 1);
  return Array.from({ length: limit }, (_, i) => points[Math.round(i * step)]);
}

export function latenessSeries(results: RequestRecord[]): SeriesPoint[] {
  return results
    .filter((r) => r.category !== "NOT_DISPATCHED" && typeof r.lateness_ms === "number" && typeof r.sent_offset_s === "number")
    .map((r) => ({ x: r.sent_offset_s as number, y: r.lateness_ms as number }))
    .sort((a, b) => a.x - b.x);
}

// ---------------------------------------------------------------- outcomes

export interface CategoryCount {
  category: Category;
  count: number;
}

export function outcomeCounts(exp: ExperimentResult): CategoryCount[] {
  return ALL_CATEGORIES.map((category) => ({ category, count: exp.summary.category_counts[category] ?? 0 })).filter((c) => c.count > 0);
}

export interface ErrorGroup {
  category: Category;
  detail: string;
  count: number;
}

/** Errors and timeouts, grouped by category and the recorded detail text. */
export function errorGroups(results: RequestRecord[]): ErrorGroup[] {
  const failing: Category[] = ["TIMEOUT", "CONNECTION_ERROR", "SERVER_ERROR", "CLIENT_ERROR", "UNKNOWN"];
  const map = new Map<string, ErrorGroup>();
  for (const r of results) {
    if (!failing.includes(r.category)) continue;
    const detail = r.detail ?? "(no detail recorded)";
    const key = `${r.category}|${detail}`;
    const group = map.get(key) ?? { category: r.category, detail, count: 0 };
    group.count += 1;
    map.set(key, group);
  }
  return [...map.values()].sort((a, b) => b.count - a.count);
}

export function latencies(exp: ExperimentResult, kind: "send" | "intended" = "send"): number[] {
  return numbers(
    exp.results
      .filter((r) => r.http_status != null)
      .map((r) => (kind === "send" ? r.latency_ms : r.intended_arrival_latency_ms)),
  );
}

// ---------------------------------------------------------------- comparison

export interface CompareRow {
  label: string;
  unit: "ms" | "/s" | "count" | "ratio" | "s";
  baseline: number | null;
  candidate: number | null;
  /** true when a larger number is the better direction (throughput), false for latency/errors. */
  higherIsBetter: boolean | null;
}

export function compareRows(a: ExperimentResult, b: ExperimentResult): CompareRow[] {
  const s = (e: ExperimentResult) => e.summary;
  const row = (label: string, unit: CompareRow["unit"], pick: (e: ExperimentResult) => number | null | undefined, higher: boolean | null): CompareRow => ({
    label,
    unit,
    baseline: pick(a) ?? null,
    candidate: pick(b) ?? null,
    higherIsBetter: higher,
  });
  return [
    row("Requests sent", "count", (e) => s(e).total_requests, null),
    row("Successful registrations", "count", (e) => s(e).successful_requests, null),
    row("Completed requests / s", "/s", (e) => s(e).completed_requests_per_second, true),
    row("Successful registrations / s", "/s", (e) => s(e).successful_registrations_per_second, true),
    row("Latency p50 (send-time)", "ms", (e) => s(e).latency_ms?.p50, false),
    row("Latency p95 (send-time)", "ms", (e) => s(e).latency_ms?.p95, false),
    row("Latency p99 (send-time)", "ms", (e) => s(e).latency_ms?.p99, false),
    row("Latency average (send-time)", "ms", (e) => s(e).latency_ms?.average, false),
    row("Queue-full refusals", "count", (e) => s(e).category_counts.QUEUE_FULL ?? 0, false),
    row("Admission-control refusals", "count", (e) => s(e).category_counts.ADMISSION_REJECTED ?? 0, false),
    row("Timeouts", "count", (e) => s(e).category_counts.TIMEOUT ?? 0, false),
    row("Offered rate", "/s", (e) => s(e).open_loop?.offered_rate_per_s, null),
    row("Achieved dispatch rate", "/s", (e) => s(e).open_loop?.achieved_dispatch_rate_per_s, null),
    row("Max dispatch lateness", "ms", (e) => s(e).open_loop?.lateness_ms?.max, false),
    row("Elapsed", "s", (e) => s(e).elapsed_seconds, null),
    // Present only for runs started through the demo API, which records the server's settings in the file.
    ...(a.server && b.server
      ? [
          row("Server: queue capacity", "count", (e) => e.server?.os_layer.queue_capacity, null),
          row("Server: worker threads", "count", (e) => e.server?.os_layer.worker_count, null),
          row("Server: DB permits", "count", (e) => e.server?.os_layer.db_semaphore_permits, null),
        ]
      : []),
  ];
}

/** Why two runs might not be comparable. Empty list = nothing obvious found (not a proof). */
export function comparabilityWarnings(a: ExperimentResult, b: ExperimentResult): string[] {
  const out: string[] = [];
  if (a.config.seed !== b.config.seed) out.push(`Seeds differ (${a.config.seed} vs ${b.config.seed}): the request targets are different.`);
  if (a.config.arrival_model !== b.config.arrival_model) out.push("Arrival models differ (open vs closed loop).");
  if (a.config.pattern !== b.config.pattern) out.push(`Patterns differ (${a.config.pattern} vs ${b.config.pattern}).`);
  if (a.config.request_count !== b.config.request_count) out.push("Request counts differ.");
  if (a.config.contention !== b.config.contention) out.push("Contention settings differ.");
  const ov = (e: ExperimentResult) => e.summary.open_loop;
  if (ov(a) && !ov(a)!.valid_open_loop) out.push("The baseline run is not a valid open-loop run.");
  if (ov(b) && !ov(b)!.valid_open_loop) out.push("The candidate run is not a valid open-loop run.");
  return out;
}

// ---------------------------------------------------------------- export

const CSV_COLUMNS: (keyof RequestRecord)[] = [
  "request_id", "sequence", "student_id", "section_id", "category", "http_status", "intended_offset_s", "sent_offset_s",
  "end_offset_s", "lateness_ms", "send_time_latency_ms", "intended_arrival_latency_ms", "detail",
];

function csvCell(value: unknown): string {
  if (value == null) return "";
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Per-request results as CSV, straight from the loaded file. */
export function resultsToCsv(exp: ExperimentResult): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const r of exp.results) lines.push(CSV_COLUMNS.map((c) => csvCell(r[c])).join(","));
  return lines.join("\n") + "\n";
}
