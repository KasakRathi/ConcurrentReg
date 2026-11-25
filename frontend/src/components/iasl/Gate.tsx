import { ShieldAlert } from "lucide-react";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { fmtInt } from "@/lib/format";
import { ADMISSION_COLOR, gateGeometry } from "@/lib/iaslLogic";

const SLIDE = "transition-[width,left] duration-[400ms] ease-[var(--ease-out-quint)] motion-reduce:transition-none";

/**
 * The queue drawn as a lane. The fill is how many requests are waiting, the fuchsia marker is the admission limit,
 * and the hatched stretch beyond the marker is where a new request is turned away. It shows the one decision IASL makes.
 */
export function Gate({ depth, limit, capacity, minimum, maximum, fallback }: {
  depth: number;
  limit: number;
  capacity: number;
  minimum: number | null;
  maximum: number | null;
  fallback?: boolean;
}) {
  const g = gateGeometry(depth, limit, capacity);
  const refusedWidth = Math.max(0, 100 - g.limitPct);
  const minPct = minimum !== null && capacity > 0 ? Math.min(100, (minimum / capacity) * 100) : null;
  const maxPct = maximum !== null && capacity > 0 && maximum < capacity ? (maximum / capacity) * 100 : null;
  const unrestricted = limit >= capacity;
  const summary = `Queue lane: ${fmtInt(depth)} waiting, admission limit ${fmtInt(limit)}, queue capacity ${fmtInt(capacity)}. ${g.binding ? "New requests are being refused." : "New requests are being admitted."}`;

  return (
    <section className="panel p-5" aria-labelledby="iasl-gate-title">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="iasl-gate-title" className="text-sm font-medium text-ink-50">The gate</h2>
          <p className="mt-0.5 max-w-xl text-xs leading-relaxed text-ink-300">
            {unrestricted
              ? <>The limit equals the queue capacity, so only a physically full queue turns requests away. {fmtInt(depth)} are waiting now.</>
              : <>A request may join the queue only while fewer than <span className="font-mono text-ink-100">{fmtInt(limit)}</span> are waiting. <span className="font-mono text-ink-100">{fmtInt(depth)}</span> are waiting now.</>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {fallback && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber/30 bg-amber/[0.08] px-2.5 py-0.5 text-[11px] text-amber">
              <ShieldAlert className="size-3" aria-hidden /> Fallback limit in force
            </span>
          )}
          <SourceBadge source="live" />
        </div>
      </header>

      <div role="img" aria-label={summary}>
        <div className="relative pt-8">
          <div
            className={cn("absolute top-0 -translate-x-1/2 rounded-md px-2 py-0.5 font-mono text-[12px] font-semibold text-ink-950", SLIDE)}
            style={{ left: `${g.limitPct}%`, background: ADMISSION_COLOR }}
          >
            {fmtInt(limit)}
          </div>

          <div className="relative h-14 overflow-hidden rounded-md border border-ink-700 bg-ink-900">
            <div
              className={cn("absolute inset-y-0 left-0", SLIDE, g.binding ? "bg-rose/60" : "bg-amber/50")}
              style={{ width: `${g.depthPct}%` }}
            >
              {g.depthPct >= 12 && <span className="absolute inset-y-0 left-3 flex items-center font-mono text-[12px] text-ink-50">{fmtInt(depth)} waiting</span>}
            </div>
            <div
              className={cn("absolute inset-y-0 right-0 flex items-center justify-center", SLIDE)}
              style={{
                width: `${refusedWidth}%`,
                backgroundColor: "rgb(251 113 133 / 0.05)",
                backgroundImage: "repeating-linear-gradient(135deg, rgb(251 113 133 / 0.22) 0 5px, transparent 5px 11px)",
              }}
            >
              {refusedWidth >= 18 && <span className="rounded bg-ink-950/70 px-1.5 py-0.5 text-[11px] text-rose">refused here</span>}
            </div>
          </div>

          <div
            className={cn("absolute bottom-0 top-6 w-[3px] -translate-x-1/2 rounded-full", SLIDE)}
            style={{ left: `${g.limitPct}%`, background: ADMISSION_COLOR, boxShadow: `0 0 0 3px rgb(5 6 7 / 0.7), 0 0 14px ${ADMISSION_COLOR}66` }}
          />
        </div>

        <div className="relative mt-2 h-9 font-mono text-[11px] text-ink-300">
          {minPct !== null && minimum !== null && (
            <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${minPct}%` }}>
              <span aria-hidden className="mx-auto mb-0.5 block h-1.5 w-px bg-ink-400" />
              lowest {fmtInt(minimum)}
            </span>
          )}
          {maxPct !== null && maximum !== null && (
            <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${maxPct}%` }}>
              <span aria-hidden className="mx-auto mb-0.5 block h-1.5 w-px bg-ink-400" />
              highest {fmtInt(maximum)}
            </span>
          )}
          <span className="absolute right-0 whitespace-nowrap text-right">
            <span aria-hidden className="ml-auto mb-0.5 block h-1.5 w-px bg-ink-400" />
            capacity {fmtInt(capacity)}
          </span>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-3 border-t border-ink-800 pt-3 text-xs">
        <div><dt className="text-ink-300">Waiting now</dt><dd className="tabular mt-0.5 font-mono text-[18px] font-light text-amber">{fmtInt(depth)}</dd></div>
        <div><dt className="text-ink-300">Admission limit</dt><dd className="tabular mt-0.5 font-mono text-[18px] font-light" style={{ color: ADMISSION_COLOR }}>{fmtInt(limit)}</dd></div>
        <div><dt className="text-ink-300">Queue capacity</dt><dd className="tabular mt-0.5 font-mono text-[18px] font-light text-ink-50">{fmtInt(capacity)}</dd></div>
      </dl>
    </section>
  );
}
