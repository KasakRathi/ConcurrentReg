import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from "recharts";
import type { Sample } from "@/hooks/monitor";
import { fmtClock } from "@/lib/format";
import { COLORS } from "@/lib/theme";
import { axisProps, ChartTooltip, gridProps, Legend } from "./common";

type Key = keyof Sample;

export interface LiveSeries {
  key: Key;
  label: string;
  color: string;
}

/** A time series of polls taken by this browser. Gaps (null rates after an outage or restart) are left as gaps. */
export function LiveChart({ samples, series, height = 220, referenceY, referenceLabel, step = false }: {
  samples: Sample[];
  series: LiveSeries[];
  height?: number;
  referenceY?: number;
  referenceLabel?: string;
  step?: boolean;
}) {
  return (
    <>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={samples} margin={{ top: 8, right: 24, left: -12, bottom: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={(v: number) => fmtClock(v)} minTickGap={48} />
            <YAxis {...axisProps} width={44} allowDecimals={false} domain={[0, (max: number) => Math.max(1, Math.ceil(max * 1.15), referenceY ?? 0)]} />
            <Tooltip content={<ChartTooltip labelFormat={(v) => fmtClock(Number(v))} valueFormat={(v) => v.toLocaleString("en-US", { maximumFractionDigits: 1 })} />} cursor={{ stroke: "#3a4147" }} />
            {referenceY !== undefined && <ReferenceLine y={referenceY} stroke={COLORS.rose} strokeDasharray="4 3" label={{ value: referenceLabel, fill: COLORS.rose, fontSize: 10, position: "insideTopRight" }} />}
            {series.map((s) => (
              <Line key={s.key} type={step ? "stepAfter" : "monotone"} dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={1.8} dot={false} connectNulls={false} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <Legend items={series.map((s) => ({ color: s.color, label: s.label }))} />
    </>
  );
}
