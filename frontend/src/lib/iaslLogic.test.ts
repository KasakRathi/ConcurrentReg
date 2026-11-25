import { describe, expect, it } from "vitest";
import { ADMISSION_COLOR, agoText, describeDecision, gateGeometry, limitSeries, parseWall, RULES, signalViews, STATE_META, stateBands } from "./iaslLogic";
import { makeDecision, makeHistory, makeSignals } from "./iaslFixtures";
import type { IaslDecision, IaslSignal, IaslState } from "./iaslTypes";
import { COLORS } from "./theme";

const T = (clock: string) => new Date(`2026-11-25T${clock}`).getTime();
const transition = (id: number, at: string, from: IaslState, to: IaslState): IaslDecision =>
  makeDecision({ id, at_wall: `2026-11-25T${at}`, previous_state: from, current_state: to, action: "HOLD", new_value: 100, previous_value: 100 });

describe("STATE_META and colours", () => {
  it("names each state in plain words and uses the dashboard's meaning colours", () => {
    expect(STATE_META.HEALTHY).toMatchObject({ label: "Healthy", color: COLORS.mint, tone: "mint" });
    expect(STATE_META.UNDER_PRESSURE).toMatchObject({ label: "Under pressure", color: COLORS.amber, tone: "amber" });
    expect(STATE_META.OVERLOADED).toMatchObject({ label: "Overloaded", color: COLORS.rose, tone: "rose" });
    for (const meta of Object.values(STATE_META)) expect(meta.blurb.length).toBeGreaterThan(20);
  });
  it("the admission colour is the one used for refused-by-admission results", () => {
    expect(ADMISSION_COLOR).toBe("#e879f9");
  });
});

describe("parseWall", () => {
  it("reads server-local ISO text", () => {
    expect(parseWall("2026-11-25T10:00:03.250")).toBe(T("10:00:03.250"));
    expect(parseWall("  2026-11-25T10:00:03  ")).toBe(T("10:00:03"));
  });
  it("is NaN for anything that is not a date", () => {
    for (const bad of ["", "   ", "not a date", "2026-13-45T99:00:00", null as unknown as string, undefined as unknown as string, 5 as unknown as string]) {
      expect(Number.isNaN(parseWall(bad))).toBe(true);
    }
  });
});

describe("stateBands", () => {
  const from = T("10:00:00"), to = T("10:01:00");

  it("with no decisions the whole window is the current state", () => {
    expect(stateBands([], from, to, "HEALTHY")).toEqual([{ from, to, state: "HEALTHY" }]);
  });
  it("with no decisions and no current state there is nothing to draw", () => {
    expect(stateBands([], from, to, null)).toEqual([]);
  });
  it("an empty or reversed window gives no bands", () => {
    expect(stateBands([], from, from, "HEALTHY")).toEqual([]);
    expect(stateBands([], to, from, "HEALTHY")).toEqual([]);
    expect(stateBands([], NaN, to, "HEALTHY")).toEqual([]);
  });
  it("splits the window at each state change, using the previous state before the first one", () => {
    const d = [transition(1, "10:00:20", "HEALTHY", "UNDER_PRESSURE"), transition(2, "10:00:40", "UNDER_PRESSURE", "OVERLOADED")];
    expect(stateBands(d, from, to, "OVERLOADED")).toEqual([
      { from, to: T("10:00:20"), state: "HEALTHY" },
      { from: T("10:00:20"), to: T("10:00:40"), state: "UNDER_PRESSURE" },
      { from: T("10:00:40"), to, state: "OVERLOADED" },
    ]);
  });
  it("sorts decisions that arrive out of order and breaks ties by id", () => {
    const d = [transition(2, "10:00:40", "UNDER_PRESSURE", "OVERLOADED"), transition(1, "10:00:20", "HEALTHY", "UNDER_PRESSURE")];
    expect(stateBands(d, from, to, "OVERLOADED").map((b) => b.state)).toEqual(["HEALTHY", "UNDER_PRESSURE", "OVERLOADED"]);
    const tie = [transition(2, "10:00:30", "UNDER_PRESSURE", "OVERLOADED"), transition(1, "10:00:30", "HEALTHY", "UNDER_PRESSURE")];
    // both changes happen at the same instant: the middle state lasts zero time, so it leaves no band
    expect(stateBands(tie, from, to, "OVERLOADED")).toEqual([{ from, to: T("10:00:30"), state: "HEALTHY" }, { from: T("10:00:30"), to, state: "OVERLOADED" }]);
  });
  it("a change before the window sets the starting state", () => {
    const d = [transition(1, "09:59:00", "HEALTHY", "OVERLOADED")];
    expect(stateBands(d, from, to, "OVERLOADED")).toEqual([{ from, to, state: "OVERLOADED" }]);
  });
  it("a change exactly at the window start counts as already happened", () => {
    const d = [transition(1, "10:00:00", "HEALTHY", "UNDER_PRESSURE")];
    expect(stateBands(d, from, to, "UNDER_PRESSURE")).toEqual([{ from, to, state: "UNDER_PRESSURE" }]);
  });
  it("changes at or after the window end are ignored", () => {
    const d = [transition(1, "10:01:00", "HEALTHY", "OVERLOADED"), transition(2, "10:02:00", "OVERLOADED", "HEALTHY")];
    expect(stateBands(d, from, to, "OVERLOADED")).toEqual([{ from, to, state: "HEALTHY" }]);
  });
  it("clips to the window when changes straddle both edges", () => {
    const d = [transition(1, "09:59:30", "HEALTHY", "UNDER_PRESSURE"), transition(2, "10:00:30", "UNDER_PRESSURE", "OVERLOADED"), transition(3, "10:01:30", "OVERLOADED", "HEALTHY")];
    expect(stateBands(d, from, to, "HEALTHY")).toEqual([
      { from, to: T("10:00:30"), state: "UNDER_PRESSURE" },
      { from: T("10:00:30"), to, state: "OVERLOADED" },
    ]);
  });
  it("merges adjacent bands of the same state", () => {
    // two decisions both announce "UNDER_PRESSURE": the second does not start a new band
    const d = [transition(1, "10:00:20", "HEALTHY", "UNDER_PRESSURE"), transition(2, "10:00:30", "HEALTHY", "UNDER_PRESSURE")];
    expect(stateBands(d, from, to, "UNDER_PRESSURE")).toEqual([
      { from, to: T("10:00:20"), state: "HEALTHY" },
      { from: T("10:00:20"), to, state: "UNDER_PRESSURE" },
    ]);
  });
  it("a decision that does not change the state never splits a band", () => {
    const d = [transition(1, "10:00:20", "HEALTHY", "UNDER_PRESSURE"), makeDecision({ id: 2, at_wall: "2026-11-25T10:00:30", previous_state: "UNDER_PRESSURE", current_state: "UNDER_PRESSURE" })];
    expect(stateBands(d, from, to, "UNDER_PRESSURE")).toHaveLength(2);
  });
  it("ignores decisions whose time cannot be read", () => {
    const d = [makeDecision({ at_wall: "garbage", previous_state: "HEALTHY", current_state: "OVERLOADED" })];
    expect(stateBands(d, from, to, "HEALTHY")).toEqual([{ from, to, state: "HEALTHY" }]);
  });
  it("without transitions it falls back to the first decision's state, not to the current one", () => {
    const d = [makeDecision({ previous_state: "UNDER_PRESSURE", current_state: "UNDER_PRESSURE" })];
    expect(stateBands(d, from, to, "HEALTHY")).toEqual([{ from, to, state: "UNDER_PRESSURE" }]);
  });
});

describe("describeDecision", () => {
  it("a decrease is a tightening, in the admission colour, with the server's own reason as the detail", () => {
    const d = describeDecision(makeDecision({ action: "DECREASE", previous_value: 143, new_value: 105, reason: "overloaded: queue_utilization=0.91" }));
    expect(d).toEqual({ headline: "Lowered the limit from 143 to 105", detail: "overloaded: queue_utilization=0.91", tone: "fuchsia", kind: "tightened" });
  });
  it("an increase is a relaxing", () => {
    const d = describeDecision(makeDecision({ action: "INCREASE", previous_value: 105, new_value: 124 }));
    expect(d).toMatchObject({ headline: "Raised the limit from 105 to 124", tone: "mint", kind: "relaxed" });
  });
  it("fallback and reset", () => {
    expect(describeDecision(makeDecision({ action: "FALLBACK_ENTER" }))).toMatchObject({ headline: "Entered fallback mode", tone: "rose", kind: "fallback" });
    expect(describeDecision(makeDecision({ action: "FALLBACK_EXIT" }))).toMatchObject({ headline: "Left fallback mode", tone: "mint", kind: "fallback" });
    expect(describeDecision(makeDecision({ action: "RESET" }))).toMatchObject({ kind: "reset", tone: "neutral" });
  });
  it("a state change is announced with the state names and takes the new state's colour", () => {
    const d = describeDecision(makeDecision({ action: "HOLD", previous_state: "HEALTHY", current_state: "UNDER_PRESSURE" }));
    expect(d).toMatchObject({ headline: "State changed from Healthy to Under pressure", tone: "amber", kind: "state" });
    expect(describeDecision(makeDecision({ action: "HOLD", previous_state: "UNDER_PRESSURE", current_state: "OVERLOADED" })).tone).toBe("rose");
    expect(describeDecision(makeDecision({ action: "HOLD", previous_state: "OVERLOADED", current_state: "HEALTHY" })).tone).toBe("mint");
  });
  it("a plain hold says where the limit stays", () => {
    expect(describeDecision(makeDecision({ action: "HOLD", new_value: 105 }))).toMatchObject({ headline: "Held the limit at 105", kind: "held", tone: "neutral" });
  });
  it("every way a change can be blocked has a plain explanation", () => {
    const cases: Record<string, string> = {
      cooldown: "the last change was too recent",
      reversal_lockout: "it is still watching the effect of the last decrease",
      at_bound: "the limit is already at its bound",
      oscillation_hold: "changes are paused after repeated reversals",
      oscillation_detected: "repeated reversals have paused all changes",
      applier_rejected: "the admission controller refused the value",
    };
    for (const [reason, because] of Object.entries(cases)) {
      const d = describeDecision(makeDecision({ action: "HOLD", blocked_by: reason, guardrail: "BLOCK" }));
      expect(d).toMatchObject({ headline: `Wanted to change the limit but ${because}`, kind: "blocked", tone: "amber" });
    }
  });
  it("an unknown blocking reason still gets a sentence, and a blocked change wins over a state change", () => {
    expect(describeDecision(makeDecision({ action: "HOLD", blocked_by: "something_new" })).headline).toBe("Wanted to change the limit but a safety check blocked it");
    const both = describeDecision(makeDecision({ action: "HOLD", blocked_by: "cooldown", previous_state: "HEALTHY", current_state: "OVERLOADED" }));
    expect(both.kind).toBe("blocked");
  });
  it("never invents a reason: the detail is exactly the server's text", () => {
    for (const action of ["DECREASE", "INCREASE", "HOLD", "FALLBACK_ENTER", "FALLBACK_EXIT", "RESET"] as const) {
      expect(describeDecision(makeDecision({ action, reason: `server said ${action}` })).detail).toBe(`server said ${action}`);
    }
  });
  it("an action this dashboard does not know is shown honestly instead of crashing", () => {
    const d = describeDecision(makeDecision({ action: "TELEPORT" as never, previous_value: 1, new_value: 2 }));
    expect(d.headline).toBe("TELEPORT: 1 to 2");
  });
});

describe("RULES", () => {
  it("explains every rule id the controller can write into a decision", () => {
    for (const id of ["R0", "R1", "R1b", "R1c", "R2", "R3", "R4", "R5", "R6", "GUARD", "FALLBACK", "RESET"]) {
      expect(RULES[id], id).toBeDefined();
      expect(RULES[id].title.length).toBeGreaterThan(3);
      expect(RULES[id].text.endsWith(".")).toBe(true);
    }
  });
});

describe("signalViews", () => {
  const find = (name: string, signals: IaslSignal[] = makeSignals()) => signalViews(signals).find((s) => s.name === name)!;

  it("keeps the backend order and gives each signal a plain label", () => {
    expect(signalViews(makeSignals()).map((s) => s.label)).toEqual([
      "Queue fullness", "Queue wait, slowest 5%", "Refused by a full queue", "Error rate", "Workers busy", "Waiting for a database permit",
    ]);
  });
  it("formats ratios as percent, waits as time and the permit ratio as a multiple", () => {
    expect(find("queue_utilization").valueText).toBe("91%");
    expect(find("queue_full_rejection_rate").valueText).toBe("6.0%");
    expect(find("queue_wait_p95_s").valueText).toBe("640 ms");
    expect(find("semaphore_waiting_ratio").valueText).toBe("1.5x permits");
    expect(find("queue_wait_p95_s").pressureText).toBe("100 ms");
    expect(find("queue_wait_p95_s").overloadText).toBe("500 ms");
    expect(find("queue_utilization").overloadText).toBe("85%");
    expect(find("queue_utilization", [{ ...makeSignals()[0], value: 1.5 }]).valueText).toBe("150%");
  });
  it("shows waits of a second or more in seconds and small percentages with a decimal", () => {
    expect(find("queue_wait_p95_s", [{ ...makeSignals()[1], value: 1.5 }]).valueText).toBe("1.50 s");
    expect(find("queue_utilization", [{ ...makeSignals()[0], value: 0.005 }]).valueText).toBe("0.5%");
  });
  it("a missing value is n/a with no marker position, never zero", () => {
    const s = find("error_rate");
    expect(s).toMatchObject({ value: null, valueText: "n/a", valuePct: null, level: null });
  });
  it("scales the track so the overload threshold sits two thirds of the way along", () => {
    const s = find("queue_utilization");
    expect(s.maxScale).toBeCloseTo(0.85 * 1.5);
    expect(s.overloadPct).toBeCloseTo(100 / 1.5);
    expect(s.pressurePct).toBeCloseTo((0.5 / (0.85 * 1.5)) * 100);
  });
  it("a value exactly at a threshold lands on that threshold's mark", () => {
    const atPressure = find("queue_utilization", [{ ...makeSignals()[0], value: 0.5 }]);
    expect(atPressure.valuePct).toBeCloseTo(atPressure.pressurePct);
    const atOverload = find("queue_utilization", [{ ...makeSignals()[0], value: 0.85 }]);
    expect(atOverload.valuePct).toBeCloseTo(atOverload.overloadPct);
  });
  it("a value beyond the scale stretches it so the marker is clamped to the end and the marks move inward", () => {
    const s = find("queue_wait_p95_s", [{ ...makeSignals()[1], value: 5 }]);
    expect(s.maxScale).toBe(5);
    expect(s.valuePct).toBe(100);
    expect(s.overloadPct).toBeCloseTo(10);
  });
  it("every percentage stays within 0 to 100, even for odd input", () => {
    const odd: IaslSignal[] = [
      { name: "queue_utilization", class: "primary", value: -3, level: 0, pressure_threshold: 0.5, overload_threshold: 0.85 },
      { name: "error_rate", class: "primary", value: 1e9, level: 2, pressure_threshold: 0.02, overload_threshold: 0.1 },
    ];
    for (const v of signalViews(odd)) for (const pct of [v.valuePct, v.pressurePct, v.overloadPct]) {
      if (pct !== null) { expect(pct).toBeGreaterThanOrEqual(0); expect(pct).toBeLessThanOrEqual(100); }
    }
  });
  it("passes the level through and says whether a signal is primary or only corroborating", () => {
    expect(find("queue_utilization")).toMatchObject({ level: 2, klass: "primary" });
    expect(find("queue_utilization").help).toMatch(/primary signal/);
    expect(find("worker_utilization")).toMatchObject({ level: 2, klass: "corroborating" });
    expect(find("worker_utilization").help).toMatch(/corroborating signal/);
    expect(find("semaphore_waiting_ratio").level).toBe(1);
  });
  it("copes with a signal this dashboard has never heard of", () => {
    const v = signalViews([{ name: "brand_new_signal", class: "primary", value: 0.5, level: 0, pressure_threshold: 1, overload_threshold: 2 }])[0];
    expect(v.label).toBe("brand new signal");
    expect(v.valueText).toBe("0.50");
  });
  it("an empty list is an empty list", () => {
    expect(signalViews([])).toEqual([]);
  });
});

describe("gateGeometry", () => {
  it("places the fill and the limit as shares of the queue capacity and marks the refused zone beyond the limit", () => {
    expect(gateGeometry(50, 100, 200)).toEqual({ depth: 50, limit: 100, capacity: 200, depthPct: 25, limitPct: 50, refusedZonePct: 50, binding: false });
  });
  it("is binding only when the queue has reached a limit that is below capacity", () => {
    expect(gateGeometry(100, 100, 200).binding).toBe(true);
    expect(gateGeometry(150, 100, 200).binding).toBe(true);
    expect(gateGeometry(99, 100, 200).binding).toBe(false);
    expect(gateGeometry(200, 200, 200).binding).toBe(false);            // limit == capacity: the queue's own bound, not admission
  });
  it("treats missing numbers as empty and a missing limit as the capacity", () => {
    expect(gateGeometry(null, null, 200)).toMatchObject({ depth: 0, limit: 200, depthPct: 0, limitPct: 100, refusedZonePct: 0, binding: false });
  });
  it("is safe with no capacity", () => {
    expect(gateGeometry(5, 5, 0)).toEqual({ depth: 5, limit: 5, capacity: 0, depthPct: 0, limitPct: 0, refusedZonePct: 0, binding: false });
    expect(gateGeometry(5, 5, null).capacity).toBe(0);
    expect(gateGeometry(NaN, NaN, NaN)).toMatchObject({ depth: 0, capacity: 0, binding: false });
  });
  it("clamps to the lane", () => {
    expect(gateGeometry(500, 500, 200)).toMatchObject({ depthPct: 100, limitPct: 100, refusedZonePct: 0 });
    expect(gateGeometry(-4, -1, 200)).toMatchObject({ depth: 0, depthPct: 0 });
  });
  it("a limit of zero refuses everything beyond an empty queue", () => {
    expect(gateGeometry(0, 0, 200)).toMatchObject({ limitPct: 0, refusedZonePct: 100, binding: true });
  });
});

describe("agoText", () => {
  const now = 1_000_000_000;
  it("reads naturally at each scale", () => {
    expect(agoText(now, now)).toBe("just now");
    expect(agoText(now - 4_999, now)).toBe("just now");
    expect(agoText(now - 12_000, now)).toBe("12 s ago");
    expect(agoText(now - 59_000, now)).toBe("59 s ago");
    expect(agoText(now - 180_000, now)).toBe("3 min ago");
    expect(agoText(now - 7_300_000, now)).toBe("2 h ago");
  });
  it("a time in the future is just now, and garbage is unknown", () => {
    expect(agoText(now + 60_000, now)).toBe("just now");
    expect(agoText(NaN, now)).toBe("unknown");
  });
});

describe("limitSeries", () => {
  it("turns utilisation into queue depth using the capacity and keeps the limit and refusals", () => {
    const rows = makeHistory(3, { queue_utilization: 0.25, admission_limit: 120, admission_rejections_per_s: 42 });
    const s = limitSeries(rows, 200);
    expect(s).toHaveLength(3);
    expect(s[0]).toMatchObject({ depth: 50, limit: 120, rejectedPerS: 42 });
    expect(s[1].t - s[0].t).toBe(500);
  });
  it("keeps nulls as nulls and has no depth without a capacity", () => {
    const rows = makeHistory(2, { queue_utilization: null, admission_limit: null, admission_rejections_per_s: null });
    expect(limitSeries(rows, 200)[0]).toMatchObject({ depth: null, limit: null, rejectedPerS: null });
    expect(limitSeries(makeHistory(1), null)[0].depth).toBeNull();
  });
  it("drops rows whose time cannot be read and handles an empty history", () => {
    const rows = [...makeHistory(2), { ...makeHistory(1)[0], wall_time: "broken" }];
    expect(limitSeries(rows, 200)).toHaveLength(2);
    expect(limitSeries([], 200)).toEqual([]);
  });
});
