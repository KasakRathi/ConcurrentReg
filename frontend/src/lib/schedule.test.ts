import { describe, expect, it } from "vitest";
import fixtures from "./__fixtures__/schedule.fixtures.json";
import { arrivalOffsets, phasePlan, plannedRequestCount, validateConfig } from "./schedule";
import { DEFAULT_CONFIG } from "./command";
import type { WorkloadConfig } from "./types";

type Case = { config: WorkloadConfig; planned_request_count: number; offsets: number[] | null; phase_plan: unknown[] | null };
const cases = Object.entries(fixtures).filter(([name]) => !name.startsWith("_")) as [string, Case][];

describe("schedule preview matches the Python generator", () => {
  for (const [name, fx] of cases) {
    it(`${name}: planned request count`, () => {
      expect(plannedRequestCount(fx.config)).toBe(fx.planned_request_count);
    });
    if (fx.offsets) {
      it(`${name}: every intended arrival offset is bit-identical`, () => {
        const mine = arrivalOffsets(fx.config);
        const planned = fx.planned_request_count;
        // For non-phase patterns the generator uses request_count; both must agree on length first.
        expect(mine.length).toBe(planned);
        expect(mine).toEqual(fx.offsets);
      });
    }
    if (fx.phase_plan) {
      it(`${name}: phase plan`, () => {
        expect(phasePlan(fx.config.phases)).toEqual(fx.phase_plan);
      });
    }
  }
});

describe("validateConfig mirrors validate_config()", () => {
  it("accepts every config the Python generator accepted", () => {
    for (const [name, fx] of cases) expect(validateConfig(fx.config), name).toEqual([]);
  });
  it("rejects the same obvious mistakes", () => {
    const bad = (patch: Partial<WorkloadConfig>) => validateConfig({ ...DEFAULT_CONFIG, ...patch });
    expect(bad({ request_count: 0 }).length).toBeGreaterThan(0);
    expect(bad({ request_count: 10_001 }).length).toBeGreaterThan(0);
    expect(bad({ concurrency: 1001 }).length).toBeGreaterThan(0);
    expect(bad({ pattern: "steady", rate: 0 }).length).toBeGreaterThan(0);
    expect(bad({ pattern: "phases", phases: [] }).length).toBeGreaterThan(0);
    expect(bad({ pattern: "phases", phases: [[10, 5]], arrival_model: "closed" }).length).toBeGreaterThan(0);
    expect(bad({ arrival_model: "closed", think_time_min_s: 2, think_time_max_s: 1 }).length).toBeGreaterThan(0);
    expect(bad({ contention: "mixed", section_ids: [1, 2], hot_section_count: 2 }).length).toBeGreaterThan(0);
    expect(bad({ section_ids: [1, 1] }).length).toBeGreaterThan(0);
    expect(bad({ seed: -1 }).length).toBeGreaterThan(0);
  });
});
