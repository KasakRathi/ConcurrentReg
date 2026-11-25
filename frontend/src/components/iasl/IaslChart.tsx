import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartFrame, ChartTooltip, axisProps, gridProps, Legend } from "@/components/charts/common";
import { EmptyState } from "@/components/ui/States";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { fmtClock } from "@/lib/format";
import { ADMISSION_COLOR, limitSeries, parseWall, STATE_META, stateBands } from "@/lib/iaslLogic";
import type { IaslDecision, IaslHistoryRow, IaslState, IaslStatus } from "@/lib/iaslTypes";
import { COLORS } from "@/lib/theme";

const STATES: IaslState[] = ["HEALTHY", "UNDER_PRESSURE", "OVERLOADED"];

/**
 * The last minute of the controller: the admission limit it set (fuchsia steps) against the queue it was holding back (amber),
 * with the state it judged shaded behind both, and a thin line wherever it changed the limit.
 */
export function IaslChart({ history, decisions, status }: { history: IaslHistoryRow[]; decisions: IaslDecision[]; status: IaslStatus }) {
  const capacity = status.admission.capacity ?? status.current_metrics?.queue_capacity ?? 0;
  const series = limitSeries(history, capacity);

  return (
    <ChartFrame
      title="Admission limit and queue depth, last minute"
      subtitle="The limit is the only thing the controller moves. The shaded background is the state it judged at the time."
      badge={<SourceBadge source="live" />}
      footer={<>Depth is the queue utilisation reported with each sample times the queue capacity. State shading is rebuilt from the decision log, so a state that lasted the whole minute without changing shows only as the latest state.</>}
    >
      {series.length < 3 ? (
        <EmptyState title="Collecting samples…">The chart needs a few seconds of history from the controller. Send some traffic to see the limit and the queue move.</EmptyState>
      ) : (
        <Plot series={series} decisions={decisions} capacity={capacity} state={status.state} />
      )}
    </ChartFrame>
  );
}

function Plot({ series, decisions, capacity, state }: { series: ReturnType<typeof limitSeries>; decisions: IaslDecision[]; capacity: number; state: IaslState | null }) {
  const from = series[0].t;
  const to = series[series.length - 1].t;
  const bands = stateBands(decisions, from, to, state);
  const changes = decisions.filter((d) => (d.action === "INCREASE" || d.action === "DECREASE") && parseWall(d.at_wall) >= from && parseWall(d.at_wall) <= to);

  return (
    <>
      <div style={{ height: 270 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={series} margin={{ top: 10, right: 36, left: -12, bottom: 0 }}>
            <CartesianGrid {...gridProps} />
            {bands.map((b, i) => (
              <ReferenceArea key={`${b.state}-${i}`} x1={b.from} x2={b.to} fill={COLORS[STATE_META[b.state].tone]} fillOpacity={0.075} stroke="none" ifOverflow="hidden" />
            ))}
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={(v: number) => fmtClock(v)} minTickGap={56} />
            <YAxis {...axisProps} width={44} allowDecimals={false} domain={[0, capacity > 0 ? capacity : (max: number) => Math.max(1, Math.ceil(max * 1.15))]} />
            <Tooltip content={<ChartTooltip labelFormat={(v) => fmtClock(Number(v))} valueFormat={(v) => v.toLocaleString("en-US", { maximumFractionDigits: 0 })} />} cursor={{ stroke: "#3a4147" }} />
            {capacity > 0 && <ReferenceLine y={capacity} stroke={COLORS.rose} strokeDasharray="4 3" />}
            {changes.map((d) => (
              <ReferenceLine key={d.id} x={parseWall(d.at_wall)} stroke={ADMISSION_COLOR} strokeOpacity={0.35} strokeDasharray="2 3" />
            ))}
            <Area type="monotone" dataKey="depth" name="Queue depth" stroke={COLORS.amber} strokeWidth={1.6} fill={COLORS.amber} fillOpacity={0.12} dot={false} isAnimationActive={false} connectNulls={false} />
            <Line type="stepAfter" dataKey="limit" name="Admission limit" stroke={ADMISSION_COLOR} strokeWidth={2.6} dot={false} isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[
        { color: ADMISSION_COLOR, label: "Admission limit" },
        { color: COLORS.amber, label: "Queue depth" },
        { color: COLORS.rose, label: "Queue capacity", dashed: true },
      ]} />
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-300" aria-label="Background shading by state">
        {STATES.map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <span className="inline-block size-3 rounded-sm border border-ink-600" style={{ background: `${COLORS[STATE_META[s].tone]}30` }} aria-hidden />
            {STATE_META[s].label}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-0 border-l border-dashed" style={{ borderColor: ADMISSION_COLOR }} aria-hidden />
          Limit changed
        </li>
      </ul>
    </>
  );
}
