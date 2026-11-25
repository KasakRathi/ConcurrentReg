import { describe, expect, it } from "vitest";
import { DEFAULT_CONFIG } from "./command";
import { configToRunRequest, DemoError, groupByFile, parseInfo, parseRun, parseState, type VerifySnapshot } from "./demoApi";
import { SCENARIOS } from "./scenarios";
import { validateConfig } from "./schedule";
import type { WorkloadConfig } from "./types";

// The seed (app/seed.py) creates 10 students and these two sections.
const SEEDED_SECTIONS = [1, 2];
const SEEDED_STUDENTS = 10;

describe("demo scenarios", () => {
  for (const s of SCENARIOS) {
    it(`${s.id}: is a configuration the generator's validation accepts and fits the seeded database`, () => {
      const r = s.request;
      const cfg = {
        ...DEFAULT_CONFIG, ...r, phases: (r.phases ?? []) as [number, number][], section_ids: r.section_ids ?? SEEDED_SECTIONS,
      } as WorkloadConfig;
      expect(validateConfig(cfg), s.id).toEqual([]);
      expect(cfg.section_ids.every((id) => SEEDED_SECTIONS.includes(id)), "section ids exist in the seed").toBe(true);
      expect(cfg.student_count).toBeLessThanOrEqual(SEEDED_STUDENTS);
      expect(cfg.request_count).toBeLessThanOrEqual(5000);                  // the server's demo cap
    });
  }
  it("ids are unique and every scenario states what to watch and what holds", () => {
    expect(new Set(SCENARIOS.map((s) => s.id)).size).toBe(SCENARIOS.length);
    for (const s of SCENARIOS) { expect(s.watch.length).toBeGreaterThan(10); expect(s.guarantee.length).toBeGreaterThan(10); }
  });
  it("the finite-seat race aims at the section with the fewest seats (section 2)", () => {
    const race = SCENARIOS.find((s) => s.id === "race")!;
    expect(race.request.section_ids?.[0]).toBe(2);
    expect(race.request.hot_section_count).toBe(1);
  });
});

describe("response checks", () => {
  const info = { controls_enabled: true, database: { dialect: "mysql", version: "8.4.11", name: "x", row_locks: true }, os_layer: { queue_capacity: 16, worker_count: 4, db_semaphore_permits: 2 }, tests: { available: true, reason: null, dialect: "mysql" } };
  it("accepts the real /demo/info shape and rejects anything else", () => {
    expect(parseInfo(info).database.dialect).toBe("mysql");
    expect(() => parseInfo({ hello: 1 })).toThrow(DemoError);
    expect(() => parseInfo("<html>")).toThrow(DemoError);
    expect(() => parseInfo({ ...info, controls_enabled: "yes" })).toThrow(DemoError);
  });
  it("rejects a malformed state and run", () => {
    expect(() => parseState({ sections: [] })).toThrow(DemoError);
    expect(() => parseRun({})).toThrow(DemoError);
    expect(parseRun({ status: "running" }).status).toBe("running");
  });
});

describe("mapping and grouping", () => {
  it("configToRunRequest copies phases (no shared references) and asks for a reset by default", () => {
    const cfg = { ...DEFAULT_CONFIG, pattern: "phases" as const, phases: [[5, 3]] as [number, number][] };
    const req = configToRunRequest(cfg);
    expect(req.reset_first).toBe(true);
    expect(req.phases).toEqual([[5, 3]]);
    expect(req.phases![0]).not.toBe(cfg.phases[0]);
    expect(configToRunRequest(cfg, false).reset_first).toBe(false);
  });
  it("groupByFile counts every status once and keeps files sorted", () => {
    const tests: NonNullable<VerifySnapshot["report"]>["tests"] = [
      { file: "tests/b.py", name: "1", status: "PASSED", reason: "", time_s: 0 }, { file: "tests/a.py", name: "2", status: "FAILED", reason: "x", time_s: 0 },
      { file: "tests/a.py", name: "3", status: "SKIPPED", reason: "r", time_s: 0 }, { file: "tests/a.py", name: "4", status: "ERROR", reason: "e", time_s: 0 },
      { file: "tests/a.py", name: "5", status: "PASSED", reason: "", time_s: 0 },
    ];
    const rows = groupByFile(tests);
    expect(rows.map((r) => r.file)).toEqual(["tests/a.py", "tests/b.py"]);
    expect(rows[0]).toEqual({ file: "tests/a.py", passed: 1, failed: 1, skipped: 1, error: 1, total: 4 });
    expect(rows.reduce((n, r) => n + r.total, 0)).toBe(tests.length);
  });
});
