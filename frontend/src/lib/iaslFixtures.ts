import type { IaslAnalysis, IaslDecision, IaslHistoryRow, IaslMetrics, IaslSignal, IaslStatus } from "./iaslTypes";

/**
 * Typed factories for tests (never used by the running dashboard: the page shows live data or an honest error, no sample data).
 * Values are realistic for a queue of 200, 8 workers, a step of 19 and a floor of 8.
 */

export function makeDecision(over: Partial<IaslDecision> = {}): IaslDecision {
  return {
    id: 1, event: "iasl_decision", at_wall: "2026-11-25T10:00:03.250", at_monotonic: 1234.5,
    previous_state: "OVERLOADED", current_state: "OVERLOADED",
    metrics_used: { signals: { queue_utilization: { value: 0.91, level: 2, pressure: 0.5, overload: 0.85 } }, quality: "OK" },
    action: "DECREASE", parameter: "admission_depth_limit", previous_value: 200, new_value: 162, rule: "R2",
    reason: "overloaded: queue_utilization=0.91; reducing by 38", guardrail: "ALLOW", blocked_by: null, suppressed_since_last: 0,
    ...over,
  };
}

export function makeSignals(): IaslSignal[] {
  return [
    { name: "queue_utilization", class: "primary", value: 0.91, level: 2, pressure_threshold: 0.5, overload_threshold: 0.85 },
    { name: "queue_wait_p95_s", class: "primary", value: 0.64, level: 2, pressure_threshold: 0.1, overload_threshold: 0.5 },
    { name: "queue_full_rejection_rate", class: "primary", value: 0.06, level: 2, pressure_threshold: 0.01, overload_threshold: 0.05 },
    { name: "error_rate", class: "primary", value: null, level: null, pressure_threshold: 0.02, overload_threshold: 0.1 },
    { name: "worker_utilization", class: "corroborating", value: 1, level: 2, pressure_threshold: 0.9, overload_threshold: 0.99 },
    { name: "semaphore_waiting_ratio", class: "corroborating", value: 1.5, level: 1, pressure_threshold: 1, overload_threshold: 3 },
  ];
}

export function makeAnalysis(over: Partial<IaslAnalysis> = {}): IaslAnalysis {
  return {
    state: "OVERLOADED", previous_state: "UNDER_PRESSURE", quality: "OK", held: false, this_sample_looks: "OVERLOADED",
    reason: "OVERLOADED (this sample looks OVERLOADED)", streaks: { worse: 0, better: 0 }, signals: makeSignals(), transition: null,
    ...over,
  };
}

export function makeStatus(over: Partial<IaslStatus> = {}): IaslStatus {
  return {
    enabled: true, attached: true, running: true, state: "HEALTHY", state_reason: "HEALTHY (this sample looks HEALTHY); no signal above its threshold",
    assessment_quality: "OK", metrics_quality: "OK",
    current_metrics: {
      queue_depth: 12, queue_capacity: 200, queue_utilization: 0.06, worker_utilization: 0.5, sem_utilization: 0.5,
      arrivals_per_s: 120, completed_per_s: 118, queue_full_rejection_rate: 0, error_rate: null, queue_wait_p95_s: 0.012,
      server_latency_p95_s: 0.03, sample_age_s: 0.2,
    },
    admission: {
      limit_in_force: 200, configured_limit: 200, capacity: 200, minimum: 8, maximum: 200, initial: 200, step: 19,
      what_it_limits: "a request is admitted only while fewer than this many requests are waiting in the queue",
    },
    fallback: { active: false, watchdog_tripped: false, mode: "baseline", fallback_limit: 200 },
    last_control_action: null, last_decision: null, last_decision_reason: null,
    loop: { sampling_interval_s: 0.5, ticks: 40, failed_ticks: 0, consecutive_failures: 0, changes: 0, blocked_changes: 0, updated_at: "2026-11-25T10:00:03.250" },
    calibration: "Thresholds and limits are PROVISIONAL defaults. They have not been calibrated or validated by experiment; treat them as starting values only.",
    ...over,
  };
}

/** `n` rows, 0.5 s apart, ending at 2026-11-25T10:01:00; the limit is 200 and the queue about 6% full unless overridden. */
export function makeHistory(n: number, over: Partial<IaslHistoryRow> = {}): IaslHistoryRow[] {
  const end = new Date("2026-11-25T10:01:00").getTime();
  return Array.from({ length: n }, (_, i) => {
    const t = new Date(end - (n - 1 - i) * 500);
    const pad = (x: number, w = 2) => String(x).padStart(w, "0");
    const wall = `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}T${pad(t.getHours())}:${pad(t.getMinutes())}:${pad(t.getSeconds())}.${pad(t.getMilliseconds(), 3)}`;
    return {
      wall_time: wall, quality: "OK", queue_utilization: 0.06, worker_utilization: 0.5, sem_utilization: 0.5, admission_limit: 200,
      arrivals_per_s: 120, completed_per_s: 118, queue_full_rejection_rate: 0, admission_rejections_per_s: 0,
      queue_wait_p95_s: 0.012, server_latency_p95_s: 0.03, ...over,
    };
  });
}

export function makeMetrics(over: Partial<IaslMetrics> = {}): IaslMetrics {
  return {
    enabled: true, sampling_interval_s: 0.5, analysis: makeAnalysis(),
    sample: {
      wall_time: "2026-11-25T10:00:03.250", age_s: 0.2, interval_s: 0.5, quality: "OK", restart: false, issues: [],
      gauges: { queue_depth: 12 }, interval: { arrivals_per_s: 120 }, window: { samples: 50 }, admission_limit: 200,
      kinds: { gauges: "instantaneous", interval: "rates", window: "sliding window" }, unavailable: { db_lock_wait: "not read by application code" },
    },
    ...over,
  };
}
