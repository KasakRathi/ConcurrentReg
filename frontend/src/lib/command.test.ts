import { describe, expect, it } from "vitest";
import fixtures from "./__fixtures__/schedule.fixtures.json";
import { buildCommand, buildServerCommand, DEFAULT_CONFIG } from "./command";
import { parseOsLayerStatus, ApiError } from "./api";
import { writeFileSync } from "node:fs";
import type { WorkloadConfig } from "./types";

describe("buildCommand", () => {
  it("only emits flags the generator defines", () => {
    const defined = new Set([
      "--base-url", "--arrival-model", "--requests", "--concurrency", "--pattern", "--phases", "--lateness-tolerance-ms", "--users",
      "--think-min", "--think-max", "--contention", "--sections", "--hot-sections", "--hot-fraction", "--duplicate-fraction",
      "--students", "--rate", "--ramp-stages", "--seed", "--timeout", "--output-dir",
    ]);
    const heavy: WorkloadConfig = { ...DEFAULT_CONFIG, pattern: "ramp", rate: 30, ramp_stages: 4, concurrency: 50, lateness_tolerance_ms: 20, contention: "mixed", section_ids: [1, 2, 3], hot_fraction: 0.7, duplicate_fraction: 0.1, student_count: 50, timeout_seconds: 9, base_url: "http://localhost:9000", output_dir: "my results", seed: 5 };
    for (const flag of buildCommand(heavy).match(/--[a-z-]+/g) ?? []) expect(defined.has(flag), flag).toBe(true);
  });
  it("round-trips: writes commands for the Python parser to re-read (see README, verification)", () => {
    const rows = Object.entries(fixtures).filter(([k]) => !k.startsWith("_")).map(([name, fx]) => ({
      name, config: (fx as { config: WorkloadConfig }).config, command: buildCommand((fx as { config: WorkloadConfig }).config),
    }));
    if (process.env.CMD_OUT) writeFileSync(process.env.CMD_OUT, JSON.stringify(rows));
    expect(rows.length).toBeGreaterThan(5);
  });
  it("closed loop does not emit open-loop flags", () => {
    const cmd = buildCommand({ ...DEFAULT_CONFIG, arrival_model: "closed", virtual_users: 4, think_time_min_s: 0.1, think_time_max_s: 0.3 });
    expect(cmd).toContain("--users 4");
    expect(cmd).not.toContain("--pattern");
    expect(cmd).not.toContain("--concurrency");
  });
  it("server command sets the three real environment variables", () => {
    expect(buildServerCommand(8, 3, 2)).toContain("QUEUE_CAPACITY=8 WORKER_COUNT=3 DB_SEMAPHORE_PERMITS=2");
  });
});

describe("parseOsLayerStatus", () => {
  const good = {
    config: { queue_capacity: 16, worker_count: 4, db_semaphore_permits: 2 },
    queue: { capacity: 16, depth: 0, max_depth: 0, accepted: 0, rejected_queue_full: 0, rejected_shutting_down: 0 },
    queue_wait: { jobs_dequeued: 0, total_s: 0, max_s: 0, average_s: null },
    workers: { configured: 4, alive: 4, active: 0, max_active: 0, jobs_started: 0, jobs_finished: 0, unexpected_errors: 0 },
    db_semaphore: { permits: 2, in_critical_section: 0, max_in_critical_section: 0, waiting: 0, max_waiting: 0, acquisitions: 0, wait_total_s: 0, wait_max_s: 0 },
  };
  it("accepts the real shape", () => expect(parseOsLayerStatus(good).queue.capacity).toBe(16));
  it("rejects anything else rather than showing it as metrics", () => {
    expect(() => parseOsLayerStatus({ hello: 1 })).toThrow(ApiError);
    expect(() => parseOsLayerStatus("<html>")).toThrow(ApiError);
    expect(() => parseOsLayerStatus({ ...good, queue: { depth: "3" } })).toThrow(ApiError);
  });
});
