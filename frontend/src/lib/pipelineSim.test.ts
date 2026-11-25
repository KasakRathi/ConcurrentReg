import { describe, expect, it } from "vitest";
import { mulberry32, PipelineSim, type SimParams } from "./pipelineSim";

const base: SimParams = { queueCapacity: 6, workers: 3, permits: 2, sections: 1, seatsPerSection: 5, lockSeconds: 0.2 };

function run(params: SimParams, offsets: number[], seed = 1, seconds = 40, hotShare = 1) {
  const sim = new PipelineSim(params, seed);
  sim.hotShare = hotShare;
  sim.loadSchedule(offsets, 0);
  const problems: string[] = [];
  for (let i = 0; i < seconds * 60; i += 1) {
    sim.step(1 / 60);
    problems.push(...sim.invariants());
  }
  return { sim, problems };
}

describe("PipelineSim", () => {
  it("never sells more seats than exist, whatever the burst (invariants hold at every step)", () => {
    const { sim, problems } = run(base, new Array(60).fill(0));
    expect(problems).toEqual([]);
    expect(sim.counters.registered).toBe(5);
  });
  it("a burst larger than the queue plus the workers is refused, not queued without limit", () => {
    const { sim } = run(base, new Array(60).fill(0));
    expect(sim.counters.refused).toBeGreaterThan(0);
    expect(sim.maxQueueDepth).toBeLessThanOrEqual(base.queueCapacity);
  });
  it("accounts for every request: offered = registered + full + refused once idle", () => {
    const { sim } = run(base, Array.from({ length: 40 }, (_, i) => i * 0.1));
    expect(sim.idle).toBe(true);
    expect(sim.counters.offered).toBe(40);
    expect(sim.counters.registered + sim.counters.full + sim.counters.refused).toBe(40);
  });
  it("holds with several sections, different seeds and tight resources", () => {
    for (const seed of [1, 2, 3, 4, 5]) {
      const { problems } = run({ ...base, sections: 3, permits: 1, workers: 2, queueCapacity: 3 }, Array.from({ length: 80 }, (_, i) => (i % 10) * 0.05 + Math.floor(i / 10) * 0.7), seed, 30, 0.6);
      expect(problems, `seed ${seed}`).toEqual([]);
    }
  });
  it("replays identically for the same seed", () => {
    const a = run({ ...base, sections: 2 }, new Array(30).fill(0), 9, 20, 0.5).sim.counters;
    const b = run({ ...base, sections: 2 }, new Array(30).fill(0), 9, 20, 0.5).sim.counters;
    expect(a).toEqual(b);
  });
  it("mulberry32 is deterministic and in [0,1)", () => {
    const r1 = mulberry32(5);
    const r2 = mulberry32(5);
    for (let i = 0; i < 100; i += 1) {
      const v = r1();
      expect(v).toBe(r2());
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
});
