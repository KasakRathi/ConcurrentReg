import { Clock, Dice5, SlidersHorizontal } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Reveal } from "@/components/ui/Reveal";
import { buildCommand, DEFAULT_CONFIG } from "@/lib/command";
import { arrivalOffsets, phasePlan, plannedRequestCount, scheduleRateBins, validateConfig } from "@/lib/schedule";
import { CopyButton } from "./CodeWindow";
import { SectionHead } from "./SectionHead";

const CONFIG = { ...DEFAULT_CONFIG, pattern: "phases" as const, phases: [[10, 5], [100, 2], [10, 10]] as [number, number][], contention: "hot" as const, seed: 42 };

/** A faithful window onto the Workloads page: the schedule below is computed by the same code the dashboard uses. */
export function WorkloadsSection() {
  const { bins, count, span, problems, command, plan } = useMemo(() => {
    const offsets = arrivalOffsets(CONFIG);
    return { bins: scheduleRateBins(offsets, 0.5), count: plannedRequestCount(CONFIG), span: Math.max(...offsets), problems: validateConfig(CONFIG), command: buildCommand(CONFIG), plan: phasePlan(CONFIG.phases) };
  }, []);
  const max = Math.max(...bins.map((b) => b.rate));
  return (
    <section id="workloads" className="lp-wrap scroll-mt-20 py-24 sm:py-36">
      <SectionHead tile="schedule" tileLabel="A plate with a burst of bars of different heights, one lit violet." title="Configure workloads visually">
        Choose an arrival pattern, set rates and phases, and preview the exact schedule before a single request is sent.
      </SectionHead>

      <Reveal className="mx-auto mt-14 max-w-[1108px]">
        <div className="lp-card !rounded-[28px]">
          <div className="flex items-center justify-between gap-3 border-b border-[var(--lp-line-soft)] px-4 py-3.5">
            <span className="inline-flex items-center gap-2 rounded-xl border border-[var(--lp-line-soft)] bg-white/[0.03] px-3 py-2 text-[14px] text-[#a1a4a5]"><SlidersHorizontal className="size-4" /> Presets</span>
            <span className="hidden text-[14px] text-[#a1a4a5] sm:block">Recovery workload</span>
            <div className="flex items-center gap-2">
              <span className="hidden items-center gap-2 pr-2 text-[14px] text-[#a1a4a5] md:inline-flex"><Dice5 className="size-4" /> seed {CONFIG.seed}</span>
              <Link to="/dashboard/workloads" className="rounded-lg border border-[var(--lp-line-soft)] px-3 py-2 text-[14px] text-white transition hover:bg-white/10">Open builder</Link>
            </div>
          </div>

          <div className="px-4 py-8 sm:px-8 sm:py-12">
            <div className="mx-auto max-w-[664px] overflow-hidden rounded-[28px] border border-[var(--lp-line-soft)] bg-[#050505]">
              <dl className="divide-y divide-[var(--lp-line-soft)] px-6 text-[14px]">
                {[["Arrival", "open loop · phases"], ["Phases", CONFIG.phases.map(([r, d]) => `${r}:${d}`).join(", ")], ["Contention", "hot · section 1"]].map(([k, v]) => (
                  <div key={k} className="flex items-center gap-6 py-3.5"><dt className="w-24 text-[#a1a4a5]">{k}</dt><dd className="font-mono text-[13px] text-white">{v}</dd></div>
                ))}
              </dl>
              <div className="relative h-[215px] border-t border-[var(--lp-line-soft)] bg-[radial-gradient(ellipse_at_70%_20%,rgba(167,139,250,0.18),transparent_60%)] px-6 pt-6">
                <p className="eyebrow">Intended arrival rate</p>
                <div className="mt-3 flex h-[140px] items-end gap-[3px]" role="img" aria-label={`Intended arrival rate over ${span.toFixed(0)} seconds: calm, a spike of 100 requests per second, then calm again.`}>
                  {bins.map((b) => (
                    <span key={b.t} style={{ height: `${Math.max(3, (b.rate / max) * 100)}%` }} className="flex-1 rounded-t-[2px] bg-gradient-to-t from-violet/30 to-violet" title={`${b.t}s: ${b.rate} /s`} />
                  ))}
                </div>
              </div>
              <div className="bg-white px-6 pb-8 pt-6 text-black">
                <p className="text-[15px] text-neutral-500">Validation</p>
                <p className="mt-2 text-[16px]">{problems.length === 0 ? <>The generator would accept this and send <b>{count}</b> requests over {span.toFixed(0)} s.</> : problems[0]}</p>
                <table className="mt-4 w-full text-left text-[12.5px] text-neutral-600">
                  <thead><tr className="text-neutral-400"><th className="py-1 font-medium">Phase</th><th className="font-medium">Rate</th><th className="font-medium">Window</th><th className="text-right font-medium">Requests</th></tr></thead>
                  <tbody className="font-mono">{plan.map((p) => <tr key={p.index}><td className="py-1">{p.index + 1}</td><td>{p.rate_per_s}/s</td><td>[{p.start_s}, {p.end_s})</td><td className="text-right">{p.requests}</td></tr>)}</tbody>
                </table>
                <div className="mt-5 flex items-start justify-between gap-3 rounded-xl bg-neutral-100 p-3">
                  <code className="min-w-0 whitespace-pre-wrap break-words font-mono text-[12px] leading-5 text-neutral-800">{command.replace(/ \\\n\s+/g, " ")}</code>
                  <CopyButton text={command} label="Copy the command" />
                </div>
                <p className="mt-3 flex items-center gap-1.5 text-[12px] text-neutral-500"><Clock className="size-3.5" /> Schedule computed in your browser with the generator's own rules; the generator itself produces the real one.</p>
              </div>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
