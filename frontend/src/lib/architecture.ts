/**
 * The real request lifecycle of ConcurrentReg, written from the code (app/main.py, app/os_layer/*,
 * app/registration_service.py, app/models.py). Anything that does not exist yet is marked `status: "planned"`
 * and is shown as such. Nothing here is a claim about performance.
 */

export type Layer = "client" | "os" | "dbms";
export type StageStatus = "implemented" | "planned";

export interface MetricRef {
  /** Path inside the GET /os-layer/status response, or null when the number is not exposed by the API. */
  path: string | null;
  label: string;
  note?: string;
}

export interface Stage {
  id: string;
  name: string;
  short: string;
  layer: Layer;
  status: StageStatus;
  source: string;
  responsibility: string;
  parameters: { name: string; value: string; note?: string }[];
  metrics: MetricRef[];
  guarantees?: string[];
  limits?: string[];
}

export const LAYER_LABEL: Record<Layer, string> = {
  client: "Client side",
  os: "OS layer (server threads)",
  dbms: "DBMS layer (MySQL / InnoDB)",
};

export const STAGES: Stage[] = [
  {
    id: "generator",
    name: "Workload generator",
    short: "Client",
    layer: "client",
    status: "implemented",
    source: "workload/workload_generator.py",
    responsibility:
      "An external client that sends seeded, repeatable registration traffic to POST /registrations and records the outcome of every request. It never touches the database and has no admission control, queue or retry logic. Its thread pool creates client traffic only; it is not the server's worker pool.",
    parameters: [
      { name: "arrival model", value: "open | closed", note: "open: fixed intended arrival times. closed: N virtual users that wait for each response." },
      { name: "pattern (open)", value: "steady | burst | ramp | phases" },
      { name: "--concurrency", value: "1 to 1000", note: "cap on requests in flight; a late dispatch is measured as lateness, never hidden." },
      { name: "--seed", value: "whole number", note: "fixes the schedule, think times and request targets." },
    ],
    metrics: [
      { path: null, label: "Result file per run", note: "Read by the dashboard from an imported JSON file." },
    ],
    limits: ["Workloads are synthetic. They are not claimed to represent real university traffic."],
  },
  {
    id: "api",
    name: "FastAPI endpoint",
    short: "API",
    layer: "os",
    status: "implemented",
    source: "app/main.py",
    responsibility:
      "POST /registrations hands the request to the OS layer and awaits the answer. It does no database work itself. GET /os-layer/status returns a read-only snapshot of the layer's counters.",
    parameters: [
      { name: "201", value: "Registration successful" },
      { name: "409", value: "Already registered, or course section is full" },
      { name: "404", value: "Unknown student or section" },
      { name: "503", value: "Request queue is full (provisional) or shutting down" },
    ],
    metrics: [{ path: "config", label: "Configured limits" }],
    limits: ["The 503 for a full queue is a provisional choice; the final response is an open decision."],
  },
  {
    id: "admission",
    name: "Admission controller",
    short: "Admission",
    layer: "os",
    status: "implemented",
    source: "app/os_layer/request_pipeline.py (hook) + app/iasl/ (policy), optional",
    responsibility:
      "An OPTIONAL step in front of the queue (IASL, off by default). When IASL_ENABLED=1 a deterministic, rule-based controller moves one admission depth limit, and a request is admitted only while fewer than that many are waiting in the queue; a refusal is HTTP 503 with its own message and is counted apart from a full queue. With IASL off every request goes straight to the queue.",
    parameters: [
      { name: "IASL_ENABLED", value: "off by default", note: "set to 1 to install the admission controller and its control loop." },
      { name: "admission depth limit", value: "between the worker count and the queue capacity", note: "the only thing IASL changes; settings are IASL_* environment variables with provisional, uncalibrated defaults." },
    ],
    metrics: [
      { path: "admission.limit", label: "Admission limit in force (only when IASL is on)" },
      { path: "admission.rejected", label: "Requests refused by admission control (only when IASL is on)" },
    ],
    limits: [
      "Not shown to be better in general: see docs/iasl/IASL_EXPERIMENTS.md for what was measured, including where it did not help.",
      "It cannot raise throughput, and there is no learned policy, request classification, or resizing of the queue, workers or semaphore.",
    ],
  },
  {
    id: "queue",
    name: "Bounded queue",
    short: "Queue",
    layer: "os",
    status: "implemented",
    source: "app/os_layer/bounded_queue.py",
    responsibility:
      "Holds accepted requests waiting for a worker, first in, first out. When it is full the next request is refused immediately instead of waiting.",
    parameters: [{ name: "QUEUE_CAPACITY", value: "default 16", note: "environment variable, read once at start-up. An experimental parameter, not a recommendation." }],
    metrics: [
      { path: "queue.depth", label: "Depth now" },
      { path: "queue.max_depth", label: "Maximum depth" },
      { path: "queue.accepted", label: "Accepted" },
      { path: "queue.rejected_queue_full", label: "Refused: queue full" },
      { path: "queue_wait.average_s", label: "Average queue wait" },
    ],
    limits: ["FIFO ordering is used for now; the final fairness policy is undecided."],
  },
  {
    id: "workers",
    name: "Worker pool",
    short: "Workers",
    layer: "os",
    status: "implemented",
    source: "app/os_layer/worker_pool.py",
    responsibility: "Server-side threads that take requests off the queue. This is server concurrency, separate from how many client threads the generator uses.",
    parameters: [{ name: "WORKER_COUNT", value: "default 4", note: "fixed while the server runs." }],
    metrics: [
      { path: "workers.active", label: "Active now" },
      { path: "workers.max_active", label: "Maximum active" },
      { path: "workers.jobs_finished", label: "Jobs finished" },
      { path: "workers.unexpected_errors", label: "Unexpected errors" },
    ],
  },
  {
    id: "semaphore",
    name: "DB semaphore",
    short: "Semaphore",
    layer: "os",
    status: "implemented",
    source: "app/os_layer/db_semaphore.py",
    responsibility:
      "Limits how many workers are inside the database section at once. A worker holds a permit only while it runs the registration transaction; a request waiting in the queue holds none.",
    parameters: [{ name: "DB_SEMAPHORE_PERMITS", value: "default 2", note: "the whole registration call is the protected block for now (an open decision)." }],
    metrics: [
      { path: "db_semaphore.in_critical_section", label: "Holding a permit" },
      { path: "db_semaphore.waiting", label: "Waiting for a permit" },
      { path: "db_semaphore.max_waiting", label: "Maximum waiting" },
      { path: "db_semaphore.wait_total_s", label: "Total wait" },
    ],
  },
  {
    id: "transaction",
    name: "Registration transaction",
    short: "Transaction",
    layer: "dbms",
    status: "implemented",
    source: "app/registration_service.py",
    responsibility:
      "One MySQL transaction per request: look up the student, lock the section row with SELECT ... FOR UPDATE, check for a duplicate and for free seats, insert the registration and decrease the seat count by exactly one, then commit once, or roll back.",
    parameters: [{ name: "isolation", value: "MySQL default", note: "no isolation-level experiments exist yet." }],
    metrics: [{ path: null, label: "Lock-wait time", note: "InnoDB exposes it, but the API does not report it yet." }],
    guarantees: ["The seat check and the seat decrease happen while the row lock is held.", "The insert and the decrease commit together or not at all."],
  },
  {
    id: "innodb",
    name: "InnoDB constraints",
    short: "Constraints",
    layer: "dbms",
    status: "implemented",
    source: "app/models.py",
    responsibility: "The database is the authority on correctness, whatever the application does. Two constraints are the last line of defence.",
    parameters: [
      { name: "UNIQUE(student_id, section_id)", value: "uq_student_section", note: "a student cannot hold two registrations for one section." },
      { name: "CHECK(available_seats)", value: "ck_seats_in_range", note: "0 <= seats <= capacity." },
    ],
    metrics: [{ path: null, label: "Constraint violations", note: "Not reported by the API." }],
    guarantees: ["Successful registrations for a section never exceed its capacity (established by the test suite on MySQL, not claimed for every workload)."],
  },
];

export function getStage(id: string) {
  return STAGES.find((s) => s.id === id);
}

/** Read a dotted path out of the status object. */
export function readPath(obj: unknown, path: string): number | null {
  let cur: unknown = obj;
  for (const part of path.split(".")) {
    if (typeof cur !== "object" || cur === null) return null;
    cur = (cur as Record<string, unknown>)[part];
  }
  return typeof cur === "number" ? cur : null;
}
