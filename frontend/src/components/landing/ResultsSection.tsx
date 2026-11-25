import { BarChart3, ChevronDown, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { useResults } from "@/hooks/results-store";
import { MiniAreaThroughput } from "@/components/charts/ResultCharts";
import { Reveal } from "@/components/ui/Reveal";
import { fmtInt, fmtMs, fmtNum } from "@/lib/format";
import type { ExperimentResult } from "@/lib/types";
import { SectionHeadLeft } from "./SectionHead";

interface View { id: string; total: number; ok: number; full: number; dup: number; refused: number; rate: string; p95: string; real: boolean; exp?: ExperimentResult }

function useView(): View {
  const { items } = useResults();
  const exp = items[0]?.exp;
  if (!exp) return { id: "burst · hot · seed 42", total: 40, ok: 7, full: 29, dup: 4, refused: 0, rate: "603", p95: "56 ms", real: false };
  const c = exp.summary.category_counts;
  return {
    id: exp.experiment_id.split("-").slice(0, 3).join(" · "),
    total: exp.summary.total_requests, ok: c.SUCCESS ?? 0, full: c.COURSE_FULL ?? 0, dup: c.DUPLICATE ?? 0, refused: c.QUEUE_FULL ?? 0,
    rate: fmtNum(exp.summary.completed_requests_per_second, 1), p95: fmtMs(exp.summary.latency_ms?.p95), real: true, exp,
  };
}

const Tag = ({ real }: { real: boolean }) => (
  <span className={`absolute right-5 top-5 z-10 rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] ${real ? "border-sky/30 bg-sky/10 text-sky" : "border-white/15 bg-white/[0.03] text-[#a1a4a5]"}`}>{real ? "Your latest import" : "Example layout"}</span>
);

export function ResultsSection() {
  const v = useView();
  return (
    <section id="results" className="lp-wrap scroll-mt-20 py-24 sm:py-32">
      <SectionHeadLeft title="Go beyond counting">
        Keep every run as a result file and compare them side by side.
        <br />
        Rates, percentiles and validity, shown the way the generator measured them.
      </SectionHeadLeft>
      <div className="mt-12 grid gap-8 md:grid-cols-2">
        <Reveal>
          <article>
            <div className="lp-card relative h-[300px] sm:h-[312px]">
              <Tag real={v.real} />
              <div className="absolute inset-x-8 top-14 fade-mask-y">
                <div className="flex items-center gap-4 rounded-2xl border border-[var(--lp-line-soft)] bg-white/[0.03] p-4">
                  <span className="grid size-[60px] place-items-center rounded-2xl border border-mint/40 bg-mint/10 text-mint shadow-[0_0_30px_-8px_#6ee7b7]"><Users className="size-7" /></span>
                  <div className="min-w-0"><p className="text-[15px] text-[#a1a4a5]">Experiment</p><p className="flex items-center gap-2 truncate text-[22px] font-medium text-white">{v.id} <ChevronDown className="size-4 shrink-0 text-[#a1a4a5]" /></p></div>
                </div>
                <div className="mt-6 grid grid-cols-4 gap-4 text-[13px] uppercase tracking-wide text-[#a1a4a5]">
                  <div>All requests<p className="mt-2 text-[18px] normal-case text-white">{fmtInt(v.total)}</p></div>
                  <div>Registered<p className="mt-2 text-[18px] normal-case text-mint">{fmtInt(v.ok)}</p></div>
                  <div>Course full<p className="mt-2 text-[18px] normal-case text-amber">{fmtInt(v.full)}</p></div>
                  <div className="min-w-0">Completed / s{v.exp ? <div className="-mt-3 -mb-6"><MiniAreaThroughput exp={v.exp} /></div> : <svg viewBox="0 0 90 30" className="mt-3 w-full"><path d="M2 28 L88 4" stroke="#6ee7b7" strokeWidth="1.5" fill="none" /><path d="M2 28 L88 4 V30 H2Z" fill="#6ee7b7" fillOpacity="0.12" /></svg>}</div>
                </div>
              </div>
            </div>
            <div className="px-1 pt-8"><Users className="size-5 text-[#f0f0f0]" /><h3 className="mt-4 text-[20px] text-[#f0f0f0]">Experiment history</h3><p className="mt-3 max-w-[330px] text-[14px] leading-[22px] text-[#a1a4a5]">Import result files and keep them in your browser. Open any run for its configuration, seed and every request.</p><Link to="/dashboard/experiments" className="mt-4 inline-block text-[14px] font-medium text-white underline-offset-4 hover:underline">Learn more</Link></div>
          </article>
        </Reveal>

        <Reveal delay={0.08}>
          <article>
            <div className="lp-card relative h-[300px] sm:h-[312px]">
              <Tag real={v.real} />
              <div className="absolute inset-y-0 left-8 right-0 top-14 flex gap-4 fade-mask-y">
                <div className="relative w-[346px] shrink-0 overflow-hidden rounded-3xl border border-[var(--lp-line-soft)] bg-white/[0.02] p-5">
                  <div aria-hidden className="absolute -top-6 left-1/2 size-40 rounded-full bg-mint/30 blur-3xl" />
                  <p className="relative text-[13px] uppercase tracking-wide text-[#a1a4a5]">Throughput</p>
                  <p className="relative mt-3 text-[40px] font-light leading-none text-white">{v.rate}<span className="ml-1 text-[16px] text-[#a1a4a5]">req/s</span></p>
                  <ul className="relative mt-6 space-y-3 text-[16px]">
                    {[["Registered", v.ok, "bg-mint"], ["Course full", v.full, "bg-amber"], ["Duplicate", v.dup, "bg-violet"], ["Queue full", v.refused, "bg-rose"]].map(([l, n, c]) => (
                      <li key={l as string} className="flex items-center gap-3 border-b border-white/[0.06] pb-2.5 last:border-0"><span className={`size-2 rounded-full ${c}`} /><span className="text-[#f0f0f0]">{l}</span><span className="ml-auto text-[#a1a4a5]">{fmtInt(n as number)}</span></li>
                    ))}
                  </ul>
                </div>
                <div className="w-[240px] shrink-0 rounded-3xl border border-[var(--lp-line-soft)] bg-white/[0.02] p-5">
                  <p className="text-[13px] uppercase tracking-wide text-[#a1a4a5]">Latency p95</p>
                  <p className="mt-3 text-[40px] font-light leading-none text-[#a1a4a5]">{v.p95}</p>
                  <ul className="mt-6 space-y-3 text-[16px] text-[#a1a4a5]"><li className="flex items-center gap-3"><span className="size-2 rounded-full bg-sky" />Send-time</li><li className="flex items-center gap-3"><span className="size-2 rounded-full bg-violet" />Intended-arrival</li></ul>
                </div>
              </div>
            </div>
            <div className="px-1 pt-8"><BarChart3 className="size-5 text-[#f0f0f0]" /><h3 className="mt-4 text-[20px] text-[#f0f0f0]">Run analytics</h3><p className="mt-3 max-w-[340px] text-[14px] leading-[22px] text-[#a1a4a5]">Offered versus achieved rates, latency percentiles, dispatch lateness and the reasons a run is or is not valid.</p><Link to="/dashboard/experiments" className="mt-4 inline-block text-[14px] font-medium text-white underline-offset-4 hover:underline">Learn more</Link></div>
          </article>
        </Reveal>
      </div>
    </section>
  );
}
