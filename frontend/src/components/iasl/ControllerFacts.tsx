import type { ReactNode } from "react";
import { ShieldAlert } from "lucide-react";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { fmtClock, fmtInt } from "@/lib/format";
import { ADMISSION_COLOR, agoText, describeDecision, parseWall } from "@/lib/iaslLogic";
import type { IaslStatus } from "@/lib/iaslTypes";
import { useNow } from "./StateCard";

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-3 border-t border-ink-800 py-2.5 first:border-t-0 first:pt-0 last:pb-0">
      <dt className="text-[12.5px] text-ink-300">{label}</dt>
      <dd className="min-w-0 text-[13px] leading-relaxed text-ink-100">{children}</dd>
    </div>
  );
}

const HOW: [string, string][] = [
  ["bg-rose", "Overloaded: lower the limit by two steps."],
  ["bg-amber", "Under pressure with a backing-up queue: lower it by one step."],
  ["bg-ink-400", "Under pressure from something else, or still recovering: hold."],
  ["bg-mint", "Healthy for a while: raise it by one step, slowly."],
  ["bg-ink-400", "Unreliable data: never raise it."],
];

const num = (n: number | null | undefined) => (n === null || n === undefined ? "n/a" : fmtInt(n));

export function ControllerFacts({ status }: { status: IaslStatus }) {
  const now = useNow();
  const a = status.admission;
  const f = status.fallback;
  const loop = status.loop;
  const last = status.last_control_action;
  const lastWhen = last ? parseWall(last.at_wall) : NaN;
  const overridden = a.limit_in_force !== null && a.configured_limit !== null && a.limit_in_force !== a.configured_limit;

  return (
    <section className="panel p-5" aria-labelledby="iasl-facts-title">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <h2 id="iasl-facts-title" className="text-sm font-medium text-ink-50">The controller</h2>
        <SourceBadge source="live" />
      </header>

      {f.watchdog_tripped ? (
        <div role="alert" className="mb-4 flex gap-2.5 rounded-md border border-rose/30 bg-rose/[0.06] px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-100">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-rose" aria-hidden />
          <p><span className="font-medium text-rose">The watchdog tripped.</span> The control loop stopped reporting, so the request path switched to the fallback limit of {num(f.fallback_limit)} by itself. Registrations are unaffected.</p>
        </div>
      ) : f.active ? (
        <div role="alert" className="mb-4 flex gap-2.5 rounded-md border border-amber/30 bg-amber/[0.06] px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-100">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber" aria-hidden />
          <p><span className="font-medium text-amber">Fallback is active.</span> The limit is pinned at {num(f.fallback_limit)} ({f.mode} mode) until the controller sees healthy samples again. Registrations are unaffected.</p>
        </div>
      ) : null}

      <dl>
        <Item label="Limit in force">
          <span className="tabular font-mono text-[15px]" style={{ color: ADMISSION_COLOR }}>{num(a.limit_in_force)}</span>
          {overridden && <span className="ml-2 text-ink-300">the controller set {num(a.configured_limit)}; the fallback is overriding it</span>}
        </Item>
        <Item label="Allowed range">
          <span className="tabular font-mono">{num(a.minimum)}</span> to <span className="tabular font-mono">{num(a.maximum)}</span>, moving in steps of <span className="tabular font-mono">{num(a.step)}</span>
        </Item>
        <Item label="Fallback">
          {f.active ? "On" : "Off"}, {f.mode} mode, limit <span className="tabular font-mono">{num(f.fallback_limit)}</span>
        </Item>
        <Item label="Control loop">
          <span className="tabular font-mono">{fmtInt(loop.ticks)}</span> ticks, <span className="tabular font-mono">{fmtInt(loop.failed_ticks)}</span> failed, one every {loop.sampling_interval_s} s
          {loop.consecutive_failures ? <span className="ml-2 text-amber">{fmtInt(loop.consecutive_failures)} failures in a row</span> : null}
        </Item>
        <Item label="Changes made">
          <span className="tabular font-mono">{num(loop.changes)}</span> limit changes, <span className="tabular font-mono">{num(loop.blocked_changes)}</span> blocked by the guardrails
        </Item>
        <Item label="Last action">
          {last ? (
            <>
              {describeDecision(last).headline}
              {Number.isFinite(lastWhen) && <span className="ml-2 text-ink-300">at {fmtClock(lastWhen)}, {agoText(lastWhen, now)}</span>}
            </>
          ) : (
            <span className="text-ink-300">None yet. The limit has not needed to move.</span>
          )}
        </Item>
      </dl>

      <div className="mt-5 border-t border-ink-800 pt-4">
        <h3 className="text-[12.5px] font-medium text-ink-100">How it decides</h3>
        <ul className="mt-2 space-y-1.5 text-[12.5px] leading-relaxed text-ink-300">
          {HOW.map(([dot, text]) => (
            <li key={text} className="flex gap-2.5"><span className={`mt-[7px] size-1.5 shrink-0 rounded-full ${dot}`} aria-hidden />{text}</li>
          ))}
        </ul>
        <p className="mt-2.5 text-[11.5px] leading-relaxed text-ink-300">It waits for two bad samples in a row before it worsens its view and five good ones before it improves it, and it never moves the limit twice inside the cooldown.</p>
      </div>
    </section>
  );
}
