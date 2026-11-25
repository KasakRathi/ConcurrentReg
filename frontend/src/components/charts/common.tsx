import type { ReactNode } from "react";
import { COLORS } from "@/lib/theme";

export const axisProps = {
  stroke: COLORS.axis,
  tick: { fill: COLORS.axis, fontSize: 11, fontFamily: "var(--font-mono)" },
  tickLine: false,
  axisLine: { stroke: "#262c31" },
} as const;

export const gridProps = { stroke: COLORS.grid, strokeDasharray: "2 4", vertical: false } as const;

export function ChartTooltip({ active, payload, label, labelFormat, valueFormat }: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number | string; color?: string; dataKey?: string | number }>;
  label?: string | number;
  labelFormat?: (v: string | number) => string;
  valueFormat?: (v: number, name: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-ink-600 bg-ink-850/95 px-3 py-2 text-xs shadow-xl backdrop-blur">
      {label !== undefined && <p className="mb-1 font-mono text-ink-300">{labelFormat ? labelFormat(label) : String(label)}</p>}
      {payload.map((p) => (
        <p key={String(p.dataKey)} className="flex items-center gap-2 text-ink-100">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          <span className="text-ink-300">{p.name}</span>
          <span className="tabular ml-auto pl-3 font-mono">{typeof p.value === "number" ? (valueFormat ? valueFormat(p.value, String(p.name)) : p.value.toLocaleString("en-US", { maximumFractionDigits: 2 })) : p.value}</span>
        </p>
      ))}
    </div>
  );
}

export function ChartFrame({ title, subtitle, badge, children, footer, className = "" }: { title: string; subtitle?: string; badge?: ReactNode; children: ReactNode; footer?: ReactNode; className?: string }) {
  return (
    <section className={`panel p-5 ${className}`}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-ink-50">{title}</h3>
          {subtitle && <p className="mt-0.5 max-w-xl text-xs leading-relaxed text-ink-300">{subtitle}</p>}
        </div>
        {badge}
      </header>
      {children}
      {footer && <footer className="mt-3 text-xs leading-relaxed text-ink-400">{footer}</footer>}
    </section>
  );
}

export function Legend({ items }: { items: { color: string; label: string; dashed?: boolean }[] }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-300">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: i.dashed ? "transparent" : i.color, borderTop: i.dashed ? `2px dashed ${i.color}` : undefined }} />
          {i.label}
        </li>
      ))}
    </ul>
  );
}
