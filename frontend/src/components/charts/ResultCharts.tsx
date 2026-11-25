import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { downsample, latencyHistogram, latenessSeries, rateBins, chooseBinSeconds, outcomeCounts } from "@/lib/results";
import { CATEGORY_STYLE, COLORS } from "@/lib/theme";
import type { ExperimentResult } from "@/lib/types";
import { axisProps, ChartTooltip, gridProps, Legend } from "./common";

const H = 260;

/** Offered vs dispatched vs completed requests per second, binned from the per-request records. */
export function RatesChart({ exp }: { exp: ExperimentResult }) {
  const width = chooseBinSeconds(exp.results);
  const data = rateBins(exp.results, width);
  const closed = exp.config.arrival_model === "closed";
  return (
    <>
      <div style={{ height: H }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="t" {...axisProps} tickFormatter={(v: number) => `${+v.toFixed(2)}s`} />
            <YAxis {...axisProps} width={48} />
            <Tooltip content={<ChartTooltip labelFormat={(v) => `t = ${v} s (bin ${width} s)`} valueFormat={(v) => `${v.toFixed(1)} /s`} />} cursor={{ stroke: "#3a4147" }} />
            {!closed && <Line type="stepAfter" dataKey="offered" name="Offered (intended)" stroke={COLORS.sky} strokeDasharray="4 3" dot={false} strokeWidth={1.5} isAnimationActive={false} />}
            <Line type="stepAfter" dataKey="dispatched" name="Dispatched (sent)" stroke={COLORS.amber} dot={false} strokeWidth={1.5} isAnimationActive={false} />
            <Line type="stepAfter" dataKey="completed" name="Completed (any outcome)" stroke={COLORS.violet} dot={false} strokeWidth={1.5} isAnimationActive={false} />
            <Line type="stepAfter" dataKey="succeeded" name="Registered" stroke={COLORS.mint} dot={false} strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <Legend
        items={[
          ...(closed ? [] : [{ color: COLORS.sky, label: "Offered (intended)", dashed: true }]),
          { color: COLORS.amber, label: "Dispatched (sent)" },
          { color: COLORS.violet, label: "Completed (any outcome)" },
          { color: COLORS.mint, label: "Registered" },
        ]}
      />
    </>
  );
}

export function LatencyHistogramChart({ values, p50, p95, p99 }: { values: number[]; p50?: number; p95?: number; p99?: number }) {
  const data = latencyHistogram(values);
  return (
    <div style={{ height: H }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barCategoryGap={1}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={24} />
          <YAxis {...axisProps} width={44} allowDecimals={false} />
          <Tooltip content={<ChartTooltip labelFormat={(v) => `${v} ms`} valueFormat={(v) => `${v} requests`} />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
          <Bar dataKey="count" name="Requests" fill={COLORS.violet} radius={[2, 2, 0, 0]} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.label.startsWith(">") ? COLORS.rose : COLORS.violet} />
            ))}
          </Bar>
          {p50 !== undefined && <ReferenceLine x={data.find((d) => p50 >= d.from && p50 <= d.to)?.label} stroke={COLORS.mint} strokeDasharray="3 3" label={{ value: "p50", fill: COLORS.mint, fontSize: 10, position: "top" }} />}
          {p95 !== undefined && <ReferenceLine x={data.find((d) => p95 >= d.from && p95 <= d.to)?.label} stroke={COLORS.amber} strokeDasharray="3 3" label={{ value: "p95", fill: COLORS.amber, fontSize: 10, position: "top" }} />}
          {p99 !== undefined && <ReferenceLine x={data.find((d) => p99 >= d.from && p99 <= d.to)?.label ?? data[data.length - 1]?.label} stroke={COLORS.rose} strokeDasharray="3 3" label={{ value: "p99", fill: COLORS.rose, fontSize: 10, position: "top" }} />}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LatenessChart({ exp }: { exp: ExperimentResult }) {
  const pts = downsample(latenessSeries(exp.results), 800);
  const tol = exp.summary.open_loop?.lateness_tolerance_ms;
  return (
    <div style={{ height: H }}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis type="number" dataKey="x" name="Sent at" {...axisProps} tickFormatter={(v: number) => `${+v.toFixed(1)}s`} domain={["dataMin", "dataMax"]} />
          <YAxis type="number" dataKey="y" name="Lateness" {...axisProps} width={48} unit=" ms" />
          <Tooltip content={<ChartTooltip labelFormat={() => "Dispatch lateness"} valueFormat={(v, n) => (n === "Sent at" ? `${v.toFixed(2)} s` : `${v.toFixed(1)} ms`)} />} cursor={{ stroke: "#3a4147" }} />
          {tol !== undefined && <ReferenceLine y={tol} stroke={COLORS.rose} strokeDasharray="4 3" label={{ value: `tolerance ${tol} ms`, fill: COLORS.rose, fontSize: 10, position: "insideTopRight" }} />}
          <Scatter data={pts} fill={COLORS.amber} fillOpacity={0.7} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

export function OutcomeBars({ exp }: { exp: ExperimentResult }) {
  const rows = outcomeCounts(exp);
  const total = rows.reduce((n, r) => n + r.count, 0) || 1;
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-ink-800" role="img" aria-label="Outcome distribution">
        {rows.map((r) => (
          <div key={r.category} style={{ width: `${(r.count / total) * 100}%`, background: CATEGORY_STYLE[r.category].color }} title={`${CATEGORY_STYLE[r.category].label}: ${r.count}`} />
        ))}
      </div>
      <ul className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {rows.map((r) => (
          <li key={r.category} className="flex items-baseline gap-2 text-[13px]">
            <span className="size-2 shrink-0 translate-y-px rounded-full" style={{ background: CATEGORY_STYLE[r.category].color }} />
            <span className="text-ink-100">{CATEGORY_STYLE[r.category].label}</span>
            <span className="tabular ml-auto font-mono text-ink-50">{r.count.toLocaleString("en-US")}</span>
            <span className="tabular w-14 text-right font-mono text-xs text-ink-400">{((r.count / total) * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MiniAreaThroughput({ exp }: { exp: ExperimentResult }) {
  const data = rateBins(exp.results, chooseBinSeconds(exp.results));
  return (
    <div style={{ height: 120 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="mini-g" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COLORS.mint} stopOpacity={0.35} />
              <stop offset="100%" stopColor={COLORS.mint} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="completed" stroke={COLORS.mint} strokeWidth={1.6} fill="url(#mini-g)" isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
