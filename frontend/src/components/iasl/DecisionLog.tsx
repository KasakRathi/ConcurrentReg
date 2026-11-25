import { ArrowRight } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState } from "@/components/ui/States";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/cn";
import { fmtClock, fmtInt } from "@/lib/format";
import { describeDecision, parseWall, RULES, STATE_META } from "@/lib/iaslLogic";
import type { IaslDecision, IaslState } from "@/lib/iaslTypes";
import { COLORS } from "@/lib/theme";

const SHOWN = 25;

const EDGE = {
  mint: "border-l-mint",
  amber: "border-l-amber",
  rose: "border-l-rose",
  fuchsia: "border-l-[#e879f9]",
  neutral: "border-l-ink-500",
} as const;

function clock(d: IaslDecision): string {
  const ms = parseWall(d.at_wall);
  return Number.isFinite(ms) ? fmtClock(ms) : d.at_wall.slice(11, 19);
}

function StateChip({ state }: { state: IaslState }) {
  const m = STATE_META[state];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-ink-600 px-2 py-px text-[11.5px] text-ink-100">
      <span className="size-1.5 rounded-full" style={{ background: COLORS[m.tone] }} aria-hidden />
      {m.label}
    </span>
  );
}

function Entry({ d }: { d: IaslDecision }) {
  const t = describeDecision(d);
  const rule = RULES[d.rule];
  const changed = d.new_value !== d.previous_value;
  const stateChanged = d.previous_state !== d.current_state;
  return (
    <li className={cn("border-l-2 bg-white/[0.015] px-4 py-3", EDGE[t.tone])}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <p className="text-[14px] text-ink-50">{t.headline}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            {changed ? (
              <span className="tabular inline-flex items-center gap-1.5 font-mono text-[13px] text-ink-100">
                {fmtInt(d.previous_value)}<ArrowRight className="size-3.5 text-ink-300" aria-label="changed to" />{fmtInt(d.new_value)}
              </span>
            ) : (
              <span className="text-[12.5px] text-ink-300">limit stays at <span className="font-mono text-ink-100">{fmtInt(d.new_value)}</span></span>
            )}
            {stateChanged ? (
              <span className="inline-flex items-center gap-1.5">
                <StateChip state={d.previous_state} />
                <ArrowRight className="size-3.5 text-ink-300" aria-label="became" />
                <StateChip state={d.current_state} />
              </span>
            ) : (
              <StateChip state={d.current_state} />
            )}
            {rule ? (
              <Tooltip content={<><span className="font-medium text-ink-50">{rule.title}</span><br />{rule.text}</>}>
                <button type="button" className="rounded border border-ink-600 px-1.5 py-px font-mono text-[11px] text-ink-300 hover:border-ink-400 hover:text-ink-50" aria-label={`Rule ${d.rule}: ${rule.title}`}>{d.rule}</button>
              </Tooltip>
            ) : (
              <span className="rounded border border-ink-700 px-1.5 py-px font-mono text-[11px] text-ink-300">{d.rule}</span>
            )}
            {(d.guardrail === "BLOCK" || d.guardrail === "CLAMP") && (
              <span className="rounded-full border border-amber/30 bg-amber/[0.07] px-2 py-px text-[11.5px] text-amber">
                {d.guardrail === "BLOCK" ? `blocked${d.blocked_by ? `: ${d.blocked_by.replace(/_/g, " ")}` : ""}` : "limited by a guardrail"}
              </span>
            )}
          </div>
        </div>
        <div className="shrink-0 text-right text-[11.5px] text-ink-300">
          <p className="tabular font-mono text-ink-300">{clock(d)}</p>
          {d.suppressed_since_last > 0 && <p>after {fmtInt(d.suppressed_since_last)} quiet ticks</p>}
        </div>
      </div>
      <details className="group mt-2">
        <summary className="cursor-pointer select-none text-[12px] text-ink-300 hover:text-ink-100">Why</summary>
        <p className="mt-1.5 max-w-3xl text-[12.5px] leading-relaxed text-ink-300">{t.detail}</p>
      </details>
    </li>
  );
}

/** A decision that changed the limit or the state, or entered/left fallback. Everything else is a hold or a blocked attempt. */
const isChange = (d: IaslDecision) => d.action !== "HOLD" || d.previous_state !== d.current_state;

export function DecisionLog({ decisions }: { decisions: IaslDecision[] }) {
  const [all, setAll] = useState(false);
  const [view, setView] = useState<"changes" | "everything">("changes");
  const newestFirst = useMemo(() => [...decisions].reverse(), [decisions]);
  const changes = useMemo(() => newestFirst.filter(isChange), [newestFirst]);
  const visible = view === "changes" ? changes : newestFirst;
  const hidden = newestFirst.length - changes.length;
  const shown = all ? visible : visible.slice(0, SHOWN);

  return (
    <section className="panel p-5" aria-labelledby="iasl-log-title">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="iasl-log-title" className="text-sm font-medium text-ink-50">Decision log</h2>
          <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-ink-300">What the controller did and why, newest first. Quiet ticks are counted, not listed.</p>
        </div>
        <SourceBadge source="live" />
      </header>

      {decisions.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <div className="flex rounded-md border border-ink-600 p-0.5" role="group" aria-label="Which decisions to list">
            {([["changes", `Changes (${changes.length})`], ["everything", `Everything (${newestFirst.length})`]] as const).map(([key, label]) => (
              <button key={key} type="button" onClick={() => { setView(key); setAll(false); }} aria-pressed={view === key} className={cn("rounded px-2.5 py-1 text-[12px] transition", view === key ? "bg-ink-600 text-ink-50" : "text-ink-300 hover:text-ink-50")}>{label}</button>
            ))}
          </div>
          {view === "changes" && hidden > 0 && <p className="text-[12px] text-ink-300">{hidden} attempts to change the limit were blocked or held (mostly the cooldown between changes). Choose Everything to see them.</p>}
        </div>
      )}

      {decisions.length === 0 ? (
        <EmptyState title="No decisions yet">The controller only logs changes, state changes and blocked changes; quiet ticks are counted, not listed.</EmptyState>
      ) : (
        <>
          {visible.length === 0 ? (
            <EmptyState title="No changes yet">The limit has not moved and the state has not changed since the controller started.</EmptyState>
          ) : (
            <ol className="space-y-2">{shown.map((d) => <Entry key={d.id} d={d} />)}</ol>
          )}
          {visible.length > SHOWN && (
            <div className="mt-3">
              <Button size="sm" variant="ghost" onClick={() => setAll((v) => !v)} aria-expanded={all}>{all ? `Show the latest ${SHOWN}` : `Show all ${visible.length}`}</Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
