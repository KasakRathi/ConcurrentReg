import type { IaslDecision, IaslHistoryRow, IaslSignal, IaslState } from "./iaslTypes";
import { COLORS } from "./theme";

/** Pure helpers behind the IASL page: no I/O, no React. Everything here is unit-tested (iaslLogic.test.ts). */

export const STATE_META: Record<IaslState, { label: string; color: string; tone: "mint" | "amber" | "rose"; blurb: string }> = {
  HEALTHY: { label: "Healthy", color: COLORS.mint, tone: "mint", blurb: "Requests are being served without a backlog or delay." },
  UNDER_PRESSURE: { label: "Under pressure", color: COLORS.amber, tone: "amber", blurb: "A backlog or delay is building, so the admission limit may be tightened." },
  OVERLOADED: { label: "Overloaded", color: COLORS.rose, tone: "rose", blurb: "The system is past its safe operating range, so the admission limit is being tightened." },
};

/** The same fuchsia the dashboard uses for ADMISSION_REJECTED results (lib/theme.ts). */
export const ADMISSION_COLOR = "#e879f9";

/** Server-local ISO text (no zone) to epoch ms. NaN if it is not a date. */
export function parseWall(wall: string): number {
  if (typeof wall !== "string") return NaN;
  const text = wall.trim();
  return text === "" ? NaN : new Date(text).getTime();
}

export interface StateBand { from: number; to: number; state: IaslState }

/**
 * Rebuild "which state was the system in, and when" from the decision log. Every state change is logged as a decision whose
 * previous_state differs from its current_state, so the bands can be derived without any extra backend field.
 */
export function stateBands(decisions: IaslDecision[], fromMs: number, toMs: number, currentState: IaslState | null): StateBand[] {
  if (!(fromMs < toMs)) return [];
  const transitions = decisions
    .filter((d) => d.previous_state !== d.current_state)
    .map((d) => ({ t: parseWall(d.at_wall), id: d.id, from: d.previous_state, to: d.current_state }))
    .filter((x) => Number.isFinite(x.t))
    .sort((a, b) => a.t - b.t || a.id - b.id);

  let state: IaslState | null;
  const before = transitions.filter((x) => x.t <= fromMs);
  const after = transitions.filter((x) => x.t > fromMs && x.t < toMs);
  if (before.length > 0) state = before[before.length - 1].to;
  else if (after.length > 0) state = after[0].from;
  else if (decisions.length > 0) state = decisions[0].previous_state;
  else state = currentState;
  if (state === null) return [];

  const bands: StateBand[] = [];
  const push = (from: number, to: number, s: IaslState) => {
    if (!(from < to)) return;
    const last = bands[bands.length - 1];
    if (last && last.state === s && last.to === from) last.to = to;
    else bands.push({ from, to, state: s });
  };
  let cursor = fromMs;
  for (const x of after) {
    push(cursor, x.t, state);
    state = x.to;
    cursor = x.t;
  }
  push(cursor, toMs, state);
  return bands;
}

export interface DecisionText {
  headline: string;
  detail: string;
  tone: "mint" | "amber" | "rose" | "fuchsia" | "neutral";
  kind: "tightened" | "relaxed" | "held" | "blocked" | "state" | "fallback" | "reset";
}

/** Why a wanted change did not happen, as a clause that completes "Wanted to change the limit but ...". */
const BLOCKED_BECAUSE: Record<string, string> = {
  cooldown: "the last change was too recent",
  reversal_lockout: "it is still watching the effect of the last decrease",
  at_bound: "the limit is already at its bound",
  oscillation_hold: "changes are paused after repeated reversals",
  oscillation_detected: "repeated reversals have paused all changes",
  applier_rejected: "the admission controller refused the value",
  unknown_parameter: "that parameter cannot be changed",
  invalid_action: "that was not a valid change",
  invalid_target: "the target value was not valid",
  direction_mismatch: "the proposed value did not move in the intended direction",
};

export function describeDecision(d: IaslDecision): DecisionText {
  const detail = d.reason;
  switch (d.action) {
    case "DECREASE":
      return { headline: `Lowered the limit from ${d.previous_value} to ${d.new_value}`, detail, tone: "fuchsia", kind: "tightened" };
    case "INCREASE":
      return { headline: `Raised the limit from ${d.previous_value} to ${d.new_value}`, detail, tone: "mint", kind: "relaxed" };
    case "FALLBACK_ENTER":
      return { headline: "Entered fallback mode", detail, tone: "rose", kind: "fallback" };
    case "FALLBACK_EXIT":
      return { headline: "Left fallback mode", detail, tone: "mint", kind: "fallback" };
    case "RESET":
      return { headline: "Reset the controller for a new queue", detail, tone: "neutral", kind: "reset" };
    case "HOLD": {
      if (d.blocked_by) {
        const because = BLOCKED_BECAUSE[d.blocked_by] ?? "a safety check blocked it";
        return { headline: `Wanted to change the limit but ${because}`, detail, tone: "amber", kind: "blocked" };
      }
      if (d.previous_state !== d.current_state) {
        return {
          headline: `State changed from ${STATE_META[d.previous_state].label} to ${STATE_META[d.current_state].label}`,
          detail, tone: STATE_META[d.current_state].tone, kind: "state",
        };
      }
      return { headline: `Held the limit at ${d.new_value}`, detail, tone: "neutral", kind: "held" };
    }
    default:
      return { headline: `${String(d.action)}: ${d.previous_value} to ${d.new_value}`, detail, tone: "neutral", kind: "held" };
  }
}

export const RULES: Record<string, { title: string; text: string }> = {
  R0: { title: "Fallback holds the limit", text: "While in fallback mode the limit stays pinned at the safe fallback value, whatever the metrics say." },
  R1: { title: "Unreliable data: no change", text: "When the metrics are stale, invalid or incomplete the controller changes nothing, and never raises the limit on bad data." },
  R1b: { title: "Recovering: wait", text: "The state is still bad but this sample already looks healthy, so the controller neither tightens further nor relaxes yet." },
  R1c: { title: "Unconfirmed pressure: wait", text: "The state is healthy but this sample shows pressure, so it waits for confirmation and does not raise the limit meanwhile." },
  R2: { title: "Overloaded: tighten fast", text: "In the overloaded state the limit is lowered by two steps." },
  R3: { title: "Queue pressure: tighten", text: "Under pressure that comes from the queue, the limit is lowered by one step." },
  R4: { title: "Pressure not from the queue: hold", text: "When delay or errors rise but the queue is not the cause, the controller does not add admission and does not tighten either." },
  R5: { title: "Healthy: relax slowly", text: "After sustained health the limit is raised by one step, with a longer cooldown than tightening." },
  R6: { title: "Healthy at the maximum", text: "The limit is already at its maximum, so there is nothing to do." },
  GUARD: { title: "Guardrail intervened", text: "A safety rule paused changes, for example after the limit reversed direction too many times in a short while." },
  FALLBACK: { title: "Fallback mode", text: "Repeated failures or unreliable metrics put the controller in fallback; it leaves after enough consecutive healthy samples." },
  RESET: { title: "Controller reset", text: "The queue was replaced, so the limits were recomputed and control restarted from the initial value." },
};

export interface SignalView {
  name: string;
  label: string;
  klass: "primary" | "corroborating";
  value: number | null;
  valueText: string;
  level: 0 | 1 | 2 | null;
  maxScale: number;
  valuePct: number | null;
  pressurePct: number;
  overloadPct: number;
  pressureText: string;
  overloadText: string;
  help: string;
}

const SIGNAL_INFO: Record<string, { label: string; kind: "percent" | "wait" | "ratio"; what: string }> = {
  queue_utilization: { label: "Queue fullness", kind: "percent", what: "How full the queue is compared with its physical capacity." },
  queue_wait_p95_s: { label: "Queue wait, slowest 5%", kind: "wait", what: "How long the slowest 5% of recent requests waited in the queue." },
  queue_full_rejection_rate: { label: "Refused by a full queue", kind: "percent", what: "Share of arrivals turned away because the queue was physically full." },
  error_rate: { label: "Error rate", kind: "percent", what: "Share of finished requests that ended in a database error." },
  worker_utilization: { label: "Workers busy", kind: "percent", what: "Share of worker threads busy right now." },
  semaphore_waiting_ratio: { label: "Waiting for a database permit", kind: "ratio", what: "Workers waiting for a database permit, relative to the number of permits." },
};

const clampPct = (n: number) => Math.max(0, Math.min(100, n));

function formatSignal(kind: "percent" | "wait" | "ratio" | "plain", v: number): string {
  if (kind === "percent") {
    const p = v * 100;
    return `${p >= 10 ? p.toFixed(0) : p.toFixed(1)}%`;
  }
  if (kind === "wait") return v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`;
  if (kind === "ratio") return `${v.toFixed(1)}x permits`;
  return v.toFixed(2);
}

export function signalViews(signals: IaslSignal[]): SignalView[] {
  return signals.map((s) => {
    const info = SIGNAL_INFO[s.name];
    const kind = info?.kind ?? "plain";
    const maxScale = Math.max(s.overload_threshold * 1.5, s.value ?? 0, 1e-9);
    const role = s.class === "primary"
      ? "A primary signal: it can move the state on its own."
      : "A corroborating signal: it only confirms what the primary signals show.";
    return {
      name: s.name,
      label: info?.label ?? s.name.replace(/_/g, " "),
      klass: s.class,
      value: s.value,
      valueText: s.value === null ? "n/a" : formatSignal(kind, s.value),
      level: s.level,
      maxScale,
      valuePct: s.value === null ? null : clampPct((s.value / maxScale) * 100),
      pressurePct: clampPct((s.pressure_threshold / maxScale) * 100),
      overloadPct: clampPct((s.overload_threshold / maxScale) * 100),
      pressureText: formatSignal(kind, s.pressure_threshold),
      overloadText: formatSignal(kind, s.overload_threshold),
      help: `${info?.what ?? "A signal the controller watches."} ${role}`,
    };
  });
}

export interface GateGeometry {
  depth: number;
  limit: number;
  capacity: number;
  depthPct: number;
  limitPct: number;
  refusedZonePct: number;
  binding: boolean;
}

/** The queue as a lane: how full it is, where the admission limit sits, and the part beyond the limit where requests are refused. */
export function gateGeometry(depth: number | null, limit: number | null, capacity: number | null): GateGeometry {
  const cap = capacity !== null && Number.isFinite(capacity) && capacity > 0 ? capacity : 0;
  const d = depth !== null && Number.isFinite(depth) && depth > 0 ? depth : 0;
  const lim = limit !== null && Number.isFinite(limit) && limit >= 0 ? limit : cap;
  const pct = (n: number) => (cap > 0 ? clampPct((n / cap) * 100) : 0);
  const limitPct = pct(lim);
  return {
    depth: d, limit: lim, capacity: cap,
    depthPct: pct(d), limitPct, refusedZonePct: cap > 0 ? 100 - limitPct : 0,
    binding: cap > 0 && lim < cap && d >= lim,
  };
}

export function agoText(fromMs: number, nowMs: number): string {
  const s = Math.floor((nowMs - fromMs) / 1000);
  if (!Number.isFinite(s)) return "unknown";
  if (s < 5) return "just now";
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  return `${Math.floor(s / 3600)} h ago`;
}

/** Rows for the time-series chart. Queue depth is derived: the history carries utilisation, depth = utilisation x capacity. */
export function limitSeries(history: IaslHistoryRow[], capacity: number | null): { t: number; limit: number | null; depth: number | null; rejectedPerS: number | null }[] {
  const out: { t: number; limit: number | null; depth: number | null; rejectedPerS: number | null }[] = [];
  for (const r of history) {
    const t = parseWall(r.wall_time);
    if (!Number.isFinite(t)) continue;
    out.push({
      t,
      limit: r.admission_limit,
      depth: r.queue_utilization === null || capacity === null ? null : r.queue_utilization * capacity,
      rejectedPerS: r.admission_rejections_per_s,
    });
  }
  return out;
}
