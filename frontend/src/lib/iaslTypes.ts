/**
 * The JSON shapes of the read-only IASL endpoints (app/iasl_api.py, app/iasl/serialize.py, app/iasl/controller.py).
 * This file is the contract between the data layer (iaslApi.ts, hooks/iasl.tsx, iaslLogic.ts) and the UI components.
 * A value the server could not provide is null, never a made-up number.
 */

export type IaslState = "HEALTHY" | "UNDER_PRESSURE" | "OVERLOADED";
export type IaslAction = "INCREASE" | "DECREASE" | "HOLD" | "FALLBACK_ENTER" | "FALLBACK_EXIT" | "RESET";
export type IaslGuardrail = "ALLOW" | "CLAMP" | "BLOCK";
export type IaslQuality = "OK" | "DEGRADED" | "INVALID" | "RESTART" | "STALE";

/** What every /iasl/* endpoint answers (200) when IASL is switched off. */
export interface IaslOff {
  enabled: false;
  message: string;
}

export interface IaslSignalLevel {
  value: number | null;
  level: 0 | 1 | 2 | null;
  pressure: number;
  overload: number;
}

/** One entry of the decision log (GET /iasl/decisions, and last_decision / last_control_action in the status). */
export interface IaslDecision {
  id: number;
  event: string;
  at_wall: string; // ISO text in the SERVER's local time, no zone
  at_monotonic: number;
  previous_state: IaslState;
  current_state: IaslState;
  metrics_used: {
    signals?: Record<string, IaslSignalLevel>;
    quality?: IaslQuality;
    transition?: string;
    admission_limit_seen?: number | null;
    sample_issues?: string[];
    interval_s?: number | null;
  };
  action: IaslAction;
  parameter: string;
  previous_value: number;
  new_value: number;
  rule: string; // R0..R6, R1b, R1c, GUARD, FALLBACK, RESET
  reason: string;
  guardrail: IaslGuardrail | null;
  blocked_by: string | null;
  suppressed_since_last: number;
}

export interface IaslCurrentMetrics {
  queue_depth: number | null;
  queue_capacity: number | null;
  queue_utilization: number | null;
  worker_utilization: number | null;
  sem_utilization: number | null;
  arrivals_per_s: number | null;
  completed_per_s: number | null;
  queue_full_rejection_rate: number | null;
  error_rate: number | null;
  queue_wait_p95_s: number | null;
  server_latency_p95_s: number | null;
  sample_age_s?: number;
}

/** GET /iasl/status when IASL is on. */
export interface IaslStatus {
  enabled: true;
  attached: boolean;
  running: boolean;
  state: IaslState | null; // null until the first sample has been analysed
  state_reason: string;
  assessment_quality: IaslQuality | null;
  metrics_quality: IaslQuality | null;
  current_metrics: IaslCurrentMetrics | null;
  admission: {
    limit_in_force: number | null;
    configured_limit: number | null;
    capacity: number | null;
    minimum: number | null;
    maximum: number | null;
    initial: number | null;
    step: number | null;
    what_it_limits: string;
  };
  fallback: {
    active: boolean | null;
    watchdog_tripped: boolean | null;
    mode: "baseline" | "conservative";
    fallback_limit: number | null;
  };
  last_control_action: IaslDecision | null;
  last_decision: IaslDecision | null;
  last_decision_reason: string | null;
  loop: {
    sampling_interval_s: number;
    ticks: number;
    failed_ticks: number;
    consecutive_failures: number | null;
    changes: number | null;
    blocked_changes: number | null;
    updated_at: string | null;
  };
  calibration: string;
}

export interface IaslSignal {
  name: string;
  class: "primary" | "corroborating";
  value: number | null;
  level: 0 | 1 | 2 | null;
  pressure_threshold: number;
  overload_threshold: number;
}

export interface IaslAnalysis {
  state: IaslState;
  previous_state: IaslState;
  quality: IaslQuality;
  held: boolean;
  this_sample_looks: IaslState | null;
  reason: string;
  streaks: { worse: number; better: number };
  signals: IaslSignal[];
  transition: { from: IaslState; to: IaslState; at: string; reason: string } | null;
}

export interface IaslSample {
  wall_time: string;
  age_s: number | null;
  interval_s: number | null;
  quality: IaslQuality;
  restart: boolean;
  issues: string[];
  gauges: Record<string, number | null>;
  interval: Record<string, number | null> | null;
  window: Record<string, number | null>;
  admission_limit: number | null;
  kinds: { gauges: string; interval: string; window: string };
  unavailable: Record<string, string>;
}

/** One compact row of GET /iasl/metrics?history=N (oldest first). Queue DEPTH = queue_utilization x capacity. */
export interface IaslHistoryRow {
  wall_time: string;
  quality: IaslQuality;
  queue_utilization: number | null;
  worker_utilization: number | null;
  sem_utilization: number | null;
  admission_limit: number | null;
  arrivals_per_s: number | null;
  completed_per_s: number | null;
  queue_full_rejection_rate: number | null;
  admission_rejections_per_s: number | null;
  queue_wait_p95_s: number | null;
  server_latency_p95_s: number | null;
}

/** GET /iasl/metrics when IASL is on. `history` is present only when requested. */
export interface IaslMetrics {
  enabled: true;
  sample: IaslSample | null;
  analysis: IaslAnalysis | null;
  sampling_interval_s: number;
  history?: IaslHistoryRow[];
}

/** GET /iasl/decisions when IASL is on (oldest first). */
export interface IaslDecisions {
  enabled: true;
  returned: number;
  kept: number;
  note: string;
  decisions: IaslDecision[];
}

/** GET /iasl/config (answers whether or not IASL is on). */
export interface IaslConfigView {
  enabled: boolean;
  active: boolean;
  read_only: boolean;
  how_to_change: string;
  calibration: string;
  settings: Record<string, number | string | boolean | null>;
  environment_variables: Record<string, string>;
  resolved?: {
    parameter: string;
    minimum: number;
    maximum: number;
    initial: number;
    step: number;
    largest_single_move: number;
    fallback_limit: number;
    fallback_mode: string;
  };
}
