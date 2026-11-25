import { useEffect, useState } from "react";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { agoText, parseWall, STATE_META, type signalViews } from "@/lib/iaslLogic";
import type { IaslStatus } from "@/lib/iaslTypes";

const TONE = {
  mint: { text: "text-mint", dot: "bg-mint", edge: "shadow-[inset_3px_0_0_0_var(--color-mint)]" },
  amber: { text: "text-amber", dot: "bg-amber", edge: "shadow-[inset_3px_0_0_0_var(--color-amber)]" },
  rose: { text: "text-rose", dot: "bg-rose", edge: "shadow-[inset_3px_0_0_0_var(--color-rose)]" },
} as const;

/** A clock that re-renders its component once per interval, so "3 s ago" stays true between polls. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

type SignalView = ReturnType<typeof signalViews>[number];

export function StateCard({ status, signals = [] }: { status: IaslStatus; signals?: SignalView[] }) {
  const now = useNow();
  const state = status.state;
  const meta = state ? STATE_META[state] : null;
  const tone = meta ? TONE[meta.tone] : null;
  const updated = status.loop.updated_at ? parseWall(status.loop.updated_at) : NaN;
  const unreliable = status.assessment_quality !== null && status.assessment_quality !== "OK";
  const raised = signals.filter((s) => s.level !== null && s.level >= 1 && s.value !== null);
  const limit = status.admission.limit_in_force;
  const lowest = status.admission.minimum;
  const highest = status.admission.maximum;
  const atFloor = state !== null && state !== "HEALTHY" && limit !== null && lowest !== null && limit <= lowest;
  const recovering = state === "HEALTHY" && limit !== null && highest !== null && limit < highest;

  return (
    <section className={cn("panel flex flex-col p-5", tone?.edge)} aria-labelledby="iasl-state-title">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <h2 id="iasl-state-title" className="text-sm font-medium text-ink-50">What the controller sees</h2>
        <SourceBadge source="live" />
      </header>

      {!meta || !tone ? (
        <div className="flex flex-1 flex-col justify-center gap-1.5 py-4">
          <p className="text-2xl font-light tracking-tight text-ink-200">Waiting for the first sample</p>
          <p className="text-[13px] leading-relaxed text-ink-300">The controller samples the queue every {status.loop.sampling_interval_s} s. A state appears after it has seen enough samples to judge.</p>
        </div>
      ) : (
        <div className="flex flex-1 flex-col gap-3">
          <div className="flex items-center gap-3" role="status" aria-live="polite">
            <span className={cn("size-3 shrink-0 rounded-full", tone.dot, state === "OVERLOADED" && "motion-safe:animate-pulse-dot")} aria-hidden />
            <p className={cn("text-[34px] font-light leading-none tracking-tight", tone.text)}>{meta.label}</p>
          </div>
          <p className="max-w-sm text-[13.5px] leading-relaxed text-ink-200">{meta.blurb}</p>
          {unreliable && (
            <p className="rounded-md border border-amber/25 bg-amber/[0.06] px-3 py-2 text-[12.5px] leading-relaxed text-amber">
              Holding the last state: the latest sample was unreliable ({status.assessment_quality?.toLowerCase()}).
            </p>
          )}
          {raised.length > 0 && (
            <p className="text-[13px] leading-relaxed text-ink-200">
              <span className="text-ink-300">Behind it: </span>
              {raised.map((s, i) => (
                <span key={s.name}>{i > 0 && ", "}{s.label.toLowerCase()} <span className={cn("font-mono", s.level === 2 ? "text-rose" : "text-amber")}>{s.valueText}</span></span>
              ))}.
            </p>
          )}
          {atFloor && <p className="text-[13px] leading-relaxed text-ink-300">The limit is already at its lowest value ({lowest}), so there is nothing left to tighten.</p>}
          {recovering && <p className="text-[13px] leading-relaxed text-ink-300">Recovering: the limit is being raised step by step, now {limit} of up to {highest}.</p>}
          <details className="text-[12.5px] text-ink-300">
            <summary className="cursor-pointer select-none hover:text-ink-100">Technical reason</summary>
            <p className="mt-1.5 break-words font-mono text-[11.5px] leading-relaxed text-ink-300">{status.state_reason}</p>
          </details>
        </div>
      )}

      <footer className="mt-4 border-t border-ink-800 pt-3 text-xs text-ink-300">
        {Number.isFinite(updated) ? <>Last analysed {agoText(updated, now)}</> : <>No analysis yet</>}
      </footer>
    </section>
  );
}
