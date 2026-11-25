import { describe, expect, it } from "vitest";
import fixtures from "./__fixtures__/schedule.fixtures.json";
import {
  chooseBinSeconds, compareRows, downsample, errorGroups, latencyHistogram, parseExperiment, percentile,
  rateBins, resultsToCsv, ResultParseError,
} from "./results";
import { DEFAULT_CONFIG } from "./command";
import type { Category, ExperimentResult, RequestRecord } from "./types";

function record(i: number, category: Category, over: Partial<RequestRecord> = {}): RequestRecord {
  const intended = i * 0.1;
  return {
    request_id: `req-${i}`, sequence: i, student_id: "STU001", section_id: 1, planned_offset_s: intended,
    start_offset_s: intended + 0.01, end_offset_s: intended + 0.05, latency_ms: 40, http_status: category === "TIMEOUT" ? null : 201,
    category, detail: null, intended_offset_s: intended, sent_offset_s: intended + 0.01, lateness_ms: 10,
    send_time_latency_ms: 40, intended_arrival_latency_ms: 50, ...over,
  };
}

function experiment(results: RequestRecord[], id = "exp"): ExperimentResult {
  const counts: Record<string, number> = {};
  for (const r of results) counts[r.category] = (counts[r.category] ?? 0) + 1;
  return {
    experiment_id: id, config: DEFAULT_CONFIG, results,
    summary: {
      total_requests: results.length, successful_requests: counts.SUCCESS ?? 0, failed_requests: 0, category_counts: counts,
      elapsed_seconds: 2, completed_requests_per_second: 5, successful_registrations_per_second: 4,
      latency_sample_count: results.length, latency_ms: { average: 40, min: 40, max: 40, p50: 40, p95: 40, p99: 40 },
    },
  };
}

describe("percentile and the generator's latency_stats", () => {
  it("nearest-rank percentiles equal the Python numbers", () => {
    const fx = (fixtures as unknown as { _latency_sample: { values: number[]; stats: Record<string, number> } })._latency_sample;
    const sorted = [...fx.values].sort((a, b) => a - b);
    expect(percentile(sorted, 50)).toBe(fx.stats.p50);
    expect(percentile(sorted, 95)).toBe(fx.stats.p95);
    expect(percentile(sorted, 99)).toBe(fx.stats.p99);
    expect(sorted[0]).toBe(fx.stats.min);
    expect(sorted[sorted.length - 1]).toBe(fx.stats.max);
  });
});

describe("parseExperiment", () => {
  it("accepts a well-formed file", () => {
    const text = JSON.stringify(experiment([record(0, "SUCCESS")]));
    expect(parseExperiment(text).experiment_id).toBe("exp");
  });
  it("rejects non-JSON, wrong shapes and unknown categories", () => {
    expect(() => parseExperiment("nope")).toThrow(ResultParseError);
    expect(() => parseExperiment("[]")).toThrow(ResultParseError);
    expect(() => parseExperiment(JSON.stringify({ experiment_id: "x" }))).toThrow(ResultParseError);
    const bad = experiment([record(0, "SUCCESS")]);
    (bad.results[0] as { category: string }).category = "MYSTERY";
    expect(() => parseExperiment(JSON.stringify(bad))).toThrow(/Unknown result category/);
  });
});

describe("rateBins", () => {
  it("conserves counts: rate x bin width summed equals the number of events", () => {
    const rows = Array.from({ length: 50 }, (_, i) => record(i, i % 5 === 0 ? "COURSE_FULL" : "SUCCESS"));
    const width = 0.5;
    const bins = rateBins(rows, width);
    const sum = (key: "offered" | "dispatched" | "completed" | "succeeded") => bins.reduce((n, b) => n + b[key] * width, 0);
    expect(sum("offered")).toBeCloseTo(50, 9);
    expect(sum("dispatched")).toBeCloseTo(50, 9);
    expect(sum("completed")).toBeCloseTo(50, 9);
    expect(sum("succeeded")).toBeCloseTo(40, 9);
  });
  it("does not count undispatched requests as sent or completed", () => {
    const rows = [record(0, "SUCCESS"), record(1, "NOT_DISPATCHED", { end_offset_s: null, sent_offset_s: null, start_offset_s: null })];
    const bins = rateBins(rows, 1);
    expect(bins.reduce((n, b) => n + b.dispatched, 0)).toBe(1);
    expect(bins.reduce((n, b) => n + b.offered, 0)).toBe(2);
  });
  it("chooseBinSeconds keeps the bar count at or under 60", () => {
    const rows = [record(0, "SUCCESS", { end_offset_s: 95 })];
    expect(95 / chooseBinSeconds(rows)).toBeLessThanOrEqual(60);
  });
});

describe("histogram, downsample, errors, csv, compare", () => {
  it("histogram bins account for every sample", () => {
    const values = Array.from({ length: 200 }, (_, i) => (i < 199 ? 10 + (i % 7) : 5000));
    const hist = latencyHistogram(values);
    expect(hist.reduce((n, b) => n + b.count, 0)).toBe(200);
    expect(hist[hist.length - 1].label.startsWith(">")).toBe(true);
    expect(hist[hist.length - 1].count).toBe(1);
  });
  it("downsample keeps first and last", () => {
    const pts = Array.from({ length: 1000 }, (_, i) => i);
    const out = downsample(pts, 50);
    expect(out.length).toBe(50);
    expect(out[0]).toBe(0);
    expect(out[49]).toBe(999);
  });
  it("errorGroups groups by category and detail and ignores outcomes that are not errors", () => {
    const rows = [record(0, "TIMEOUT", { detail: "ReadTimeout" }), record(1, "TIMEOUT", { detail: "ReadTimeout" }), record(2, "COURSE_FULL"), record(3, "SERVER_ERROR", { detail: "boom" })];
    const groups = errorGroups(rows);
    expect(groups[0]).toEqual({ category: "TIMEOUT", detail: "ReadTimeout", count: 2 });
    expect(groups.length).toBe(2);
  });
  it("csv escapes commas, quotes and newlines", () => {
    const csv = resultsToCsv(experiment([record(0, "SERVER_ERROR", { detail: 'a,"b"\nc' })]));
    expect(csv).toContain('"a,""b""\nc"');
    expect(csv.split("\n")[0].startsWith("request_id,")).toBe(true);
  });
  it("compareRows reads the same summary fields for both runs", () => {
    const a = experiment([record(0, "SUCCESS")], "a");
    const b = experiment([record(0, "SUCCESS")], "b");
    b.summary.completed_requests_per_second = 10;
    const row = compareRows(a, b).find((r) => r.label === "Completed requests / s")!;
    expect([row.baseline, row.candidate]).toEqual([5, 10]);
  });
});
