import { SourceBadge } from "@/components/ui/SourceBadge";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/cn";
import { signalViews } from "@/lib/iaslLogic";

type View = ReturnType<typeof signalViews>[number];

const LEVEL = {
  0: { text: "text-mint", dot: "bg-mint", fill: "bg-mint/35", word: "normal" },
  1: { text: "text-amber", dot: "bg-amber", fill: "bg-amber/35", word: "under pressure" },
  2: { text: "text-rose", dot: "bg-rose", fill: "bg-rose/40", word: "overloaded" },
} as const;

const clampPct = (n: number) => Math.max(0, Math.min(100, n));

function Row({ s }: { s: View }) {
  const lv = s.level === null ? null : LEVEL[s.level];
  const label = `${s.label}: ${s.value === null ? "no data this tick" : s.valueText}. Pressure starts at ${s.pressureText}, overload at ${s.overloadText}.${lv ? ` Currently ${lv.word}.` : ""}`;
  return (
    <li className="border-t border-ink-800 py-3 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[13.5px] text-ink-50">{s.label}</span>
          <Tooltip content={s.help}>
            <button type="button" className="shrink-0 rounded-full border border-ink-600 px-2 py-px text-[11px] text-ink-300 hover:border-ink-400 hover:text-ink-50">
              {s.klass === "primary" ? "decides the state" : "backs it up"}
            </button>
          </Tooltip>
        </div>
        <span className={cn("tabular shrink-0 font-mono text-[13px]", lv ? lv.text : "text-ink-300")}>{s.value === null ? "no data this tick" : s.valueText}</span>
      </div>

      <div role="img" aria-label={label} className="relative mt-2.5 h-2 rounded-full bg-ink-800">
        {s.valuePct !== null && lv && (
          <div className={cn("absolute inset-y-0 left-0 rounded-full transition-[width] duration-300 motion-reduce:transition-none", lv.fill)} style={{ width: `${clampPct(s.valuePct)}%` }} />
        )}
        <span aria-hidden className="absolute -inset-y-1 w-px bg-amber/70" style={{ left: `${clampPct(s.pressurePct)}%` }} />
        <span aria-hidden className="absolute -inset-y-1 w-px bg-rose/70" style={{ left: `${clampPct(s.overloadPct)}%` }} />
        {s.valuePct !== null && lv && (
          <span aria-hidden className={cn("absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink-900 transition-[left] duration-300 motion-reduce:transition-none", lv.dot)} style={{ left: `${clampPct(s.valuePct)}%` }} />
        )}
      </div>

      <p className="mt-1.5 flex justify-between gap-3 text-[11.5px] text-ink-300">
        <span>pressure from <span className="font-mono text-amber/90">{s.pressureText}</span></span>
        <span>overload from <span className="font-mono text-rose/90">{s.overloadText}</span></span>
      </p>
    </li>
  );
}

export function SignalsPanel({ signals }: { signals: View[] }) {
  return (
    <section className="panel p-5" aria-labelledby="iasl-signals-title">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="iasl-signals-title" className="text-sm font-medium text-ink-50">Signals</h2>
          <p className="mt-0.5 max-w-md text-xs leading-relaxed text-ink-300">Backlog, delay, refusals and errors decide the state. Worker and database-permit load only back them up.</p>
        </div>
        <SourceBadge source="live" />
      </header>
      <ul className="mt-4">{signals.map((s) => <Row key={s.name} s={s} />)}</ul>
    </section>
  );
}
