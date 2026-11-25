import type { WorkloadConfig } from "./types";

/**
 * TypeScript port of the arrival-schedule rules in workload/workload_generator.py
 * (phase_plan, planned_request_count, arrival_offsets, validate_config).
 * It exists only to PREVIEW a schedule in the browser. The generator remains the source of truth,
 * and src/lib/schedule.test.ts checks this port against numbers produced by the Python code.
 */

export const LIMITS = {
  maxRequests: 10_000,
  maxInFlight: 1_000,
  maxVirtualUsers: 1_000,
  maxPhases: 50,
} as const;

export interface PhaseRow {
  index: number;
  rate_per_s: number;
  duration_s: number;
  start_s: number;
  end_s: number;
  requests: number;
}

export function phasePlan(phases: [number, number][]): PhaseRow[] {
  const plan: PhaseRow[] = [];
  let start = 0;
  phases.forEach(([rate, duration], index) => {
    const requests = Math.ceil(rate * duration - 1e-9);
    plan.push({ index, rate_per_s: rate, duration_s: duration, start_s: start, end_s: start + duration, requests });
    start += duration;
  });
  return plan;
}

export function plannedRequestCount(config: Pick<WorkloadConfig, "pattern" | "phases" | "request_count">): number {
  return config.pattern === "phases" ? phasePlan(config.phases).reduce((n, p) => n + p.requests, 0) : config.request_count;
}

export function arrivalOffsets(
  config: Pick<WorkloadConfig, "pattern" | "phases" | "request_count" | "rate" | "ramp_stages">,
): number[] {
  const count = config.request_count;
  if (config.pattern === "phases") {
    const out: number[] = [];
    for (const phase of phasePlan(config.phases)) {
      for (let k = 0; k < phase.requests; k += 1) out.push(phase.start_s + k / phase.rate_per_s);
    }
    return out;
  }
  if (config.pattern === "burst") return new Array<number>(count).fill(0);
  if (config.pattern === "steady") return Array.from({ length: count }, (_, i) => i / config.rate);
  const offsets: number[] = [];
  let timeSoFar = 0;
  for (let i = 0; i < count; i += 1) {
    const stage = Math.floor((i * config.ramp_stages) / count);
    const stageRate = (config.rate * (stage + 1)) / config.ramp_stages;
    offsets.push(timeSoFar);
    timeSoFar += 1 / stageRate;
  }
  return offsets;
}

export interface ScheduleBin {
  t: number;
  rate: number;
}

/** Intended arrival rate per bin, for plotting a schedule preview. */
export function scheduleRateBins(offsets: number[], binSeconds: number): ScheduleBin[] {
  if (offsets.length === 0) return [];
  const last = Math.max(...offsets);
  const count = Math.max(1, Math.floor(last / binSeconds) + 1);
  const bins: ScheduleBin[] = Array.from({ length: count }, (_, i) => ({ t: i * binSeconds, rate: 0 }));
  for (const o of offsets) bins[Math.min(count - 1, Math.floor(o / binSeconds))].rate += 1 / binSeconds;
  return bins;
}

/** Mirrors validate_config(). Returns a list of problems (empty = the generator would accept it). */
export function validateConfig(c: WorkloadConfig): string[] {
  const e: string[] = [];
  if (!/^https?:\/\//.test(c.base_url)) e.push("base_url must start with http:// or https://");
  if (c.pattern === "phases") {
    if (c.arrival_model === "closed") e.push("Phases describe scheduled arrivals, so they need the open-loop model.");
    if (c.phases.length < 1 || c.phases.length > LIMITS.maxPhases) e.push(`Phases: between 1 and ${LIMITS.maxPhases} rate:duration pairs.`);
    if (c.phases.some(([r, d]) => !(Number.isFinite(r) && Number.isFinite(d) && r > 0 && d > 0))) e.push("Each phase rate and duration must be greater than 0.");
    else {
      const n = plannedRequestCount(c);
      if (n < 1 || n > LIMITS.maxRequests) e.push(`The phases must produce between 1 and ${LIMITS.maxRequests} requests (they produce ${n}).`);
    }
  } else if (!(c.request_count >= 1 && c.request_count <= LIMITS.maxRequests && Number.isInteger(c.request_count))) {
    e.push(`Requests must be a whole number between 1 and ${LIMITS.maxRequests}.`);
  }
  if (!(Number.isInteger(c.concurrency) && c.concurrency >= 1 && c.concurrency <= LIMITS.maxInFlight)) e.push(`In-flight cap must be between 1 and ${LIMITS.maxInFlight}.`);
  if (!(Number.isInteger(c.seed) && c.seed >= 0)) e.push("Seed must be a non-negative whole number.");
  if (c.lateness_tolerance_ms < 0) e.push("Lateness tolerance must not be negative.");
  if (c.arrival_model === "closed") {
    if (!(Number.isInteger(c.virtual_users) && c.virtual_users >= 1 && c.virtual_users <= LIMITS.maxVirtualUsers)) e.push(`Virtual users must be between 1 and ${LIMITS.maxVirtualUsers}.`);
    if (!(c.think_time_min_s >= 0 && c.think_time_min_s <= c.think_time_max_s)) e.push("Think times must satisfy 0 <= min <= max.");
  }
  if (!(Number.isInteger(c.student_count) && c.student_count >= 1)) e.push("Students must be at least 1.");
  if (c.section_ids.length === 0 || new Set(c.section_ids).size !== c.section_ids.length || c.section_ids.some((s) => !Number.isInteger(s))) e.push("Sections must be a non-empty list of distinct whole numbers.");
  if (!(Number.isInteger(c.hot_section_count) && c.hot_section_count >= 1 && c.hot_section_count <= c.section_ids.length)) e.push("Hot sections must be between 1 and the number of sections.");
  if (c.contention === "mixed" && c.hot_section_count === c.section_ids.length) e.push("Mixed contention needs at least one non-hot section.");
  if (!(c.hot_fraction >= 0 && c.hot_fraction <= 1) || !(c.duplicate_fraction >= 0 && c.duplicate_fraction <= 1)) e.push("Hot and duplicate fractions must be between 0 and 1.");
  if (c.arrival_model === "open" && (c.pattern === "steady" || c.pattern === "ramp") && !(c.rate > 0)) e.push("Rate must be greater than 0 for steady and ramp patterns.");
  if (!(Number.isInteger(c.ramp_stages) && c.ramp_stages >= 1)) e.push("Ramp stages must be at least 1.");
  if (!(c.timeout_seconds > 0)) e.push("Timeout must be greater than 0.");
  return e;
}
