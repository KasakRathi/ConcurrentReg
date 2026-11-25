import type { WorkloadConfig } from "./types";

export const DEFAULT_CONFIG: WorkloadConfig = {
  // Same defaults as the dataclass WorkloadConfig in workload_generator.py (demonstration values, not research parameters).
  base_url: "http://127.0.0.1:8000",
  endpoint: "/registrations",
  request_count: 20,
  concurrency: 100,
  arrival_model: "open",
  pattern: "burst",
  contention: "hot",
  student_count: 10,
  section_ids: [1, 2],
  hot_section_count: 1,
  hot_fraction: 0.5,
  duplicate_fraction: 0,
  rate: 10,
  ramp_stages: 3,
  phases: [],
  lateness_tolerance_ms: 50,
  virtual_users: 10,
  think_time_min_s: 0,
  think_time_max_s: 0,
  seed: 42,
  timeout_seconds: 5,
  output_dir: "results",
};

const num = (n: number) => String(n);

/**
 * The exact terminal command for a configuration, using only flags that
 * `python -m workload.workload_generator --help` defines. Flags equal to the default are left out
 * so the command stays short; the generator then uses the same default itself.
 */
export function buildCommand(c: WorkloadConfig, python = ".venv/bin/python"): string {
  const d = DEFAULT_CONFIG;
  const args: string[] = [];
  const add = (flag: string, value: string) => args.push(`${flag} ${value}`);
  const quote = (s: string) => (/^[\w./:=,-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`);

  if (c.base_url !== d.base_url) add("--base-url", quote(c.base_url));
  if (c.arrival_model !== d.arrival_model) add("--arrival-model", c.arrival_model);

  if (c.arrival_model === "open") {
    if (c.pattern === "phases") {
      add("--phases", `"${c.phases.map(([r, s]) => `${num(r)}:${num(s)}`).join(",")}"`);
    } else {
      if (c.pattern !== d.pattern) add("--pattern", c.pattern);
      add("--requests", num(c.request_count));
      if (c.pattern === "steady" || c.pattern === "ramp") add("--rate", num(c.rate));
      if (c.pattern === "ramp" && c.ramp_stages !== d.ramp_stages) add("--ramp-stages", num(c.ramp_stages));
    }
    if (c.concurrency !== d.concurrency) add("--concurrency", num(c.concurrency));
    if (c.lateness_tolerance_ms !== d.lateness_tolerance_ms) add("--lateness-tolerance-ms", num(c.lateness_tolerance_ms));
  } else {
    add("--requests", num(c.request_count));
    add("--users", num(c.virtual_users));
    if (c.think_time_min_s !== d.think_time_min_s) add("--think-min", num(c.think_time_min_s));
    if (c.think_time_max_s !== c.think_time_min_s) add("--think-max", num(c.think_time_max_s));
  }

  if (c.contention !== d.contention) add("--contention", c.contention);
  if (c.section_ids.join(",") !== d.section_ids.join(",")) add("--sections", c.section_ids.join(","));
  if (c.hot_section_count !== d.hot_section_count) add("--hot-sections", num(c.hot_section_count));
  if (c.contention === "mixed" && c.hot_fraction !== d.hot_fraction) add("--hot-fraction", num(c.hot_fraction));
  if (c.duplicate_fraction !== d.duplicate_fraction) add("--duplicate-fraction", num(c.duplicate_fraction));
  if (c.student_count !== d.student_count) add("--students", num(c.student_count));
  add("--seed", num(c.seed));
  if (c.timeout_seconds !== d.timeout_seconds) add("--timeout", num(c.timeout_seconds));
  if (c.output_dir !== d.output_dir) add("--output-dir", quote(c.output_dir));

  return [`${python} -m workload.workload_generator`, ...args].join(" \\\n  ");
}

/** The server-side settings are environment variables read once at start-up (app/os_layer/layer_config.py). */
export function buildServerCommand(queueCapacity: number, workers: number, permits: number): string {
  return `QUEUE_CAPACITY=${queueCapacity} WORKER_COUNT=${workers} DB_SEMAPHORE_PERMITS=${permits} \\\n  .venv/bin/uvicorn app.main:app --port 8000`;
}
