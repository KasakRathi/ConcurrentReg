import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { SourceBadge, type Source } from "@/components/ui/SourceBadge";

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[26px] font-light tracking-tight text-ink-50 sm:text-3xl">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-ink-300">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Section({ title, source, sourceLabel, note, children, className }: { title: string; source?: Source; sourceLabel?: string; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("mb-10", className)}>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="text-[15px] font-medium text-ink-50">{title}</h2>
        {source && <SourceBadge source={source} label={sourceLabel} />}
      </div>
      {note && <p className="-mt-1 mb-3 max-w-3xl text-[12.5px] leading-relaxed text-ink-400">{note}</p>}
      {children}
    </section>
  );
}

export function Metric({ label, value, unit, sub, tone = "default", hint }: { label: string; value: ReactNode; unit?: string; sub?: ReactNode; tone?: "default" | "mint" | "amber" | "rose" | "violet"; hint?: string }) {
  const color = { default: "text-ink-50", mint: "text-mint", amber: "text-amber", rose: "text-rose", violet: "text-violet" }[tone];
  return (
    <div className="panel p-4" title={hint}>
      <p className="eyebrow">{label}</p>
      <p className={cn("tabular mt-2 font-mono text-[26px] font-light leading-none", color)}>
        {value}
        {unit && <span className="ml-1 text-sm text-ink-400">{unit}</span>}
      </p>
      {sub && <p className="mt-2 text-xs leading-snug text-ink-400">{sub}</p>}
    </div>
  );
}

export function MetricGrid({ children, cols = 4 }: { children: ReactNode; cols?: 3 | 4 | 5 }) {
  const c = { 3: "lg:grid-cols-3", 4: "lg:grid-cols-4", 5: "lg:grid-cols-5" }[cols];
  return <div className={cn("grid grid-cols-2 gap-3", c)}>{children}</div>;
}
