// Types mirror what the Python backend and workload generator really produce.
// Sources: app/os_layer/request_pipeline.py (snapshot) and workload/workload_generator.py (result file).

/** Response body of GET /os-layer/status. Counters are cumulative since the server started. */
export interface OsLayerStatus {
  config: { queue_capacity: number; worker_count: number; db_semaphore_permits: number };
  queue: {
    capacity: number;
    depth: number;
    max_depth: number;
    accepted: number;
    rejected_queue_full: number;
    rejected_shutting_down: number;
  };
  queue_wait: { jobs_dequeued: number; total_s: number; max_s: number; average_s: number | null };
  workers: {
    configured: number;
    alive: number;
    active: number;
    max_active: number;
    jobs_started: number;
    jobs_finished: number;
    unexpected_errors: number;
  };
  db_semaphore: {
    permits: number;
    in_critical_section: number;
    max_in_critical_section: number;
    waiting: number;
    max_waiting: number;
    acquisitions: number;
    wait_total_s: number;
    wait_max_s: number;
  };
}

export type Category =
  | "SUCCESS"
  | "DUPLICATE"
  | "COURSE_FULL"
  | "QUEUE_FULL"
  | "ADMISSION_REJECTED"
  | "CLIENT_ERROR"
  | "SERVER_ERROR"
  | "TIMEOUT"
  | "CONNECTION_ERROR"
  | "UNKNOWN"
  | "NOT_DISPATCHED";

export const ALL_CATEGORIES: Category[] = [
  "SUCCESS",
  "DUPLICATE",
  "COURSE_FULL",
  "QUEUE_FULL",
  "ADMISSION_REJECTED",
  "CLIENT_ERROR",
  "SERVER_ERROR",
  "TIMEOUT",
  "CONNECTION_ERROR",
  "UNKNOWN",
  "NOT_DISPATCHED",
];

export interface WorkloadConfig {
  base_url: string;
  endpoint: string;
  request_count: number;
  concurrency: number;
  arrival_model: "open" | "closed";
  pattern: "steady" | "burst" | "ramp" | "phases";
  contention: "hot" | "independent" | "mixed";
  student_count: number;
  section_ids: number[];
  hot_section_count: number;
  hot_fraction: number;
  duplicate_fraction: number;
  rate: number;
  ramp_stages: number;
  phases: [number, number][];
  lateness_tolerance_ms: number;
  virtual_users: number;
  think_time_min_s: number;
  think_time_max_s: number;
  seed: number;
  timeout_seconds: number;
  output_dir: string;
}

export interface LatencyStats {
  average: number;
  min: number;
  max: number;
  p50: number;
  p95: number;
  p99: number;
}

export interface LatenessStats {
  mean: number;
  median: number;
  p95: number | null;
  p99: number | null;
  max: number;
  samples: number;
}

export interface OpenLoopSummary {
  intended_requests: number;
  dispatched_requests: number;
  undispatched_requests: number;
  offered_rate_per_s: number | null;
  achieved_dispatch_rate_per_s: number | null;
  achieved_to_offered_ratio: number | null;
  lateness_ms: LatenessStats | null;
  lateness_tolerance_ms: number;
  requests_over_tolerance: number;
  in_flight_cap: number;
  requests_that_found_the_cap_full: number;
  errors: { timeouts: number; connection_errors: number; server_errors: number; client_errors: number; unclassified: number };
  valid_open_loop: boolean;
  validity_rule?: string;
  invalid_reasons: string[];
}

export interface ClosedLoopSummary {
  virtual_users: number;
  think_time_min_s: number;
  think_time_max_s: number;
  intended_requests: number;
  dispatched_requests: number;
  undispatched_requests: number;
  waited_for_previous_response: boolean;
  arrivals_are_response_dependent: boolean;
}

export interface ResultSummary {
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  category_counts: Partial<Record<Category, number>>;
  elapsed_seconds: number;
  completed_requests_per_second: number | null;
  successful_registrations_per_second: number | null;
  latency_sample_count: number;
  latency_ms: LatencyStats | null;
  intended_arrival_latency_ms?: LatencyStats | null;
  arrival_model?: "open" | "closed" | null;
  open_loop?: OpenLoopSummary | null;
  closed_loop?: ClosedLoopSummary | null;
}

export interface RunInfo {
  generator_version?: string;
  generator_revision?: string | null;
  arrival_model?: string;
  seed?: number;
  run_started_at?: string;
  run_ended_at?: string;
  in_flight_cap?: number | null;
  timeout_seconds?: number;
  lateness_tolerance_ms?: number | null;
  target_rate_per_s?: number | null;
  schedule?: { pattern: string; phases: unknown; intended_requests: number; last_intended_offset_s: number | null } | null;
  virtual_users?: number | null;
  think_time?: { min_s: number; max_s: number } | null;
  reproducible?: string;
  not_reproducible?: string;
}

export interface RequestRecord {
  request_id: string;
  sequence: number;
  student_id: string;
  section_id: number;
  planned_offset_s: number | null;
  started_at?: string;
  start_offset_s: number | null;
  end_offset_s: number | null;
  latency_ms: number | null;
  http_status: number | null;
  category: Category;
  detail: string | null;
  intended_offset_s?: number | null;
  sent_offset_s?: number | null;
  lateness_ms?: number | null;
  send_time_latency_ms?: number | null;
  intended_arrival_latency_ms?: number | null;
}

/** One saved experiment file, as written by workload_generator.save_results. */
export interface ExperimentResult {
  experiment_id: string;
  config: WorkloadConfig;
  summary: ResultSummary;
  results: RequestRecord[];
  run?: RunInfo;
  generated_requests?: unknown[];
  /** Added by the demo API: the server settings and database this run really used (the generator cannot know them). */
  server?: {
    os_layer: { queue_capacity: number; worker_count: number; db_semaphore_permits: number };
    database: { dialect: string; version: string | null; name: string | null; row_locks: boolean };
    started_via: string;
    reset_first: boolean;
    db_check?: { registrations_in_db: number; successes_reported_by_client: number; match: boolean | null; invariants_ok: boolean; note: string | null };
  };
}
