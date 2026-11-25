import { Download } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useResults } from "@/hooks/results-store";
import { ChartFrame } from "@/components/charts/common";
import { LatenessChart, LatencyHistogramChart, OutcomeBars, RatesChart } from "@/components/charts/ResultCharts";
import { CompareTable } from "@/components/dashboard/CompareTable";
import { PageHeader, Section } from "@/components/dashboard/parts";
import { ExperimentTiles } from "@/components/dashboard/Tiles";
import { Button, ButtonLink } from "@/components/ui/Button";
import { EmptyState, Skeleton, Unavailable } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import { fmtDateTime, fmtInt, fmtMs, fmtNum, fmtPct, fmtRate } from "@/lib/format";
import { errorGroups, latencies, percentileRows, resultsToCsv } from "@/lib/results";
import { CATEGORY_STYLE } from "@/lib/theme";
import type { ExperimentResult } from "@/lib/types";

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function PercentileTable({ title, values }: { title: string; values: number[] }) {
  const rows = percentileRows(values);
  return (
    <div>
      <p className="eyebrow mb-2">{title}</p>
      {rows.length === 0 ? <p className="text-[13px] text-ink-400">No answered requests.</p> : (
        <table className="w-full text-[13px]"><tbody>{rows.map((r) => <tr key={r.label} className="border-b border-ink-800 last:border-0"><td className="py-1.5 text-ink-300">{r.label}</td><td className="tabular py-1.5 text-right font-mono text-ink-50">{fmtMs(r.value)}</td></tr>)}</tbody></table>
      )}
      <p className="mt-2 text-[11px] text-ink-400">n = {fmtInt(values.length)}, nearest-rank percentiles.</p>
    </div>
  );
}

function Detail({ exp }: { exp: ExperimentResult }) {
  const { items } = useResults();
  const [otherId, setOtherId] = useState("");
  const other = items.find((i) => i.exp.experiment_id === (otherId || items.find((x) => x.exp.experiment_id !== exp.experiment_id)?.exp.experiment_id))?.exp;
  const s = exp.summary;
  const ol = s.open_loop;
  const errs = errorGroups(exp.results);
  const send = latencies(exp, "send");
  const intended = latencies(exp, "intended");
  const closed = exp.config.arrival_model === "closed";

  return (
    <>
      <PageHeader
        title={exp.experiment_id}
        description={<>{exp.config.arrival_model} loop · {closed ? `${exp.config.virtual_users} virtual users` : exp.config.pattern} · {exp.config.contention} contention · seed {exp.config.seed} · started {fmtDateTime(exp.run?.run_started_at)}</>}
        actions={<>
          <Button size="sm" variant="secondary" onClick={() => download(`${exp.experiment_id}.json`, JSON.stringify(exp, null, 2), "application/json")}><Download className="size-3.5" /> JSON</Button>
          <Button size="sm" variant="secondary" onClick={() => download(`${exp.experiment_id}.csv`, resultsToCsv(exp), "text/csv")}><Download className="size-3.5" /> Requests CSV</Button>
        </>}
      />

      {ol && (
        <div className={cn("mb-8 rounded-xl border px-5 py-4", ol.valid_open_loop ? "border-mint/25 bg-mint/[0.05]" : "border-rose/30 bg-rose/[0.05]")}>
          <p className={cn("text-sm font-medium", ol.valid_open_loop ? "text-mint" : "text-rose")}>{ol.valid_open_loop ? "Valid open-loop run" : "Not valid as open-loop evidence"}</p>
          {ol.invalid_reasons.length > 0 && <ul className="mt-1.5 space-y-1 text-[13px] text-ink-100">{ol.invalid_reasons.map((r) => <li key={r}>• {r}</li>)}</ul>}
          <p className="mt-2 text-xs leading-relaxed text-ink-300">{ol.validity_rule ?? "Valid only if every intended request was sent and none was sent later than the lateness tolerance."} Tolerance for this run: {ol.lateness_tolerance_ms} ms.</p>
        </div>
      )}
      {closed && <div className="mb-8 rounded-xl border border-ink-600 bg-white/[0.02] px-5 py-4 text-[13px] text-ink-200">Closed-loop run: arrivals depend on how fast the server answered, so there is no offered rate, no dispatch lateness and no open-loop validity to report.</div>}

      <Section title="Summary" source="file"><ExperimentTiles exp={exp} /></Section>

      <Section title="Rates and latency" source="file">
        <div className="grid gap-3 xl:grid-cols-2">
          <ChartFrame title={closed ? "Throughput over time" : "Offered versus achieved request rates"} subtitle={closed ? "Requests per second, binned by time since the run started." : `Offered ${fmtRate(ol?.offered_rate_per_s)} · dispatched ${fmtRate(ol?.achieved_dispatch_rate_per_s)} (${fmtPct(ol?.achieved_to_offered_ratio)} of offered). Rates are binned counts; the run averages above use (events - 1) / (last - first).`}>
            <RatesChart exp={exp} />
          </ChartFrame>
          <ChartFrame title="Latency distribution" subtitle="Send-time latency of requests that received an HTTP response. The red bar collects everything above p99." footer="Timeouts and connection errors have no response time and are left out.">
            <LatencyHistogramChart values={send} p50={s.latency_ms?.p50} p95={s.latency_ms?.p95} p99={s.latency_ms?.p99} />
          </ChartFrame>
        </div>
        <div className="panel mt-3 grid gap-6 p-5 sm:grid-cols-2">
          <PercentileTable title="Send-time latency (from the moment of sending)" values={send} />
          {intended.length > 0 ? <PercentileTable title="Intended-arrival latency (lateness + send-time)" values={intended} /> : <p className="self-center text-[13px] text-ink-400">Intended-arrival latency is recorded for open-loop runs only.</p>}
        </div>
      </Section>

      {!closed && ol && (
        <Section title="Dispatch lateness" source="file" note="How long after its intended arrival each request was actually sent. Lateness is the generator falling behind its own schedule, not server latency.">
          <div className="grid gap-3 xl:grid-cols-[1.4fr_1fr]">
            <ChartFrame title="Lateness of each dispatch (ms)"><LatenessChart exp={exp} /></ChartFrame>
            <div className="panel p-5 text-[13px]">
              <dl className="space-y-2.5">
                {([["Mean", fmtMs(ol.lateness_ms?.mean)], ["Median", fmtMs(ol.lateness_ms?.median)], ["p95", ol.lateness_ms?.p95 == null ? "not reported (fewer than 20 samples)" : fmtMs(ol.lateness_ms.p95)], ["p99", ol.lateness_ms?.p99 == null ? "not reported (fewer than 100 samples)" : fmtMs(ol.lateness_ms.p99)], ["Maximum", fmtMs(ol.lateness_ms?.max)], ["Over tolerance", `${fmtInt(ol.requests_over_tolerance)} requests`], ["Found the in-flight cap full", `${fmtInt(ol.requests_that_found_the_cap_full)} requests (cap ${ol.in_flight_cap})`], ["Never dispatched", fmtInt(ol.undispatched_requests)]] as const).map(([k, v]) => <div key={k} className="flex justify-between gap-4"><dt className="text-ink-300">{k}</dt><dd className="tabular text-right font-mono text-ink-50">{v}</dd></div>)}
              </dl>
            </div>
          </div>
        </Section>
      )}

      <Section title="Outcomes, errors and timeouts" source="file">
        <div className="grid gap-3 xl:grid-cols-2">
          <ChartFrame title="Registration outcome distribution"><OutcomeBars exp={exp} /></ChartFrame>
          <ChartFrame title="Error and timeout summary" subtitle="Requests that did not produce a normal registration answer.">
            {errs.length === 0 ? <p className="rounded-lg border border-mint/20 bg-mint/[0.04] px-4 py-3 text-[13px] text-ink-100">No timeouts, connection errors or unexpected responses in this run.</p> : (
              <table className="w-full text-[13px]"><tbody>{errs.map((g) => <tr key={g.category + g.detail} className="border-b border-ink-800 last:border-0"><td className="py-2 pr-3"><span className="mr-2 inline-block size-2 rounded-full" style={{ background: CATEGORY_STYLE[g.category].color }} />{CATEGORY_STYLE[g.category].label}</td><td className="py-2 pr-3 font-mono text-[12px] text-ink-300">{g.detail}</td><td className="tabular py-2 text-right font-mono text-ink-50">{fmtInt(g.count)}</td></tr>)}</tbody></table>
            )}
            <details className="mt-4 text-xs text-ink-300"><summary className="cursor-pointer text-ink-200">What each outcome means</summary><ul className="mt-2 space-y-1">{Object.values(CATEGORY_STYLE).map((c) => <li key={c.label}><b className="text-ink-100">{c.label}</b>: {c.meaning}</li>)}</ul></details>
          </ChartFrame>
        </div>
        <div className="mt-3"><Unavailable what="Queue depth over time for this run" requirement="Result files do not record server queue depth. Only the live Monitoring page samples it, and only while you are watching. Recording it per run would need the generator or server to log /os-layer/status during the run." /></div>
      </Section>

      <Section title="Configuration and seed" source="file">
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="panel p-5"><p className="eyebrow mb-2">Workload configuration</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-[12px] leading-5 text-ink-200">{JSON.stringify(exp.config, null, 2)}</pre></div>
          <div className="panel p-5">
            <p className="eyebrow mb-2">Run record</p>
            {exp.run ? <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-[12px] leading-5 text-ink-200">{JSON.stringify(exp.run, null, 2)}</pre> : <p className="text-[13px] text-ink-400">This file has no run block (written by an older generator). Seed {exp.config.seed}; elapsed {fmtNum(s.elapsed_seconds, 2)} s.</p>}
          </div>
        </div>
      </Section>

      <Section title="Baseline versus candidate" source="file" note="This run is the candidate. Choose a baseline from the imported experiments.">
        {!other ? <EmptyState title="Import another result file to compare">Only one experiment is loaded. <Link to="/dashboard/experiments" className="text-mint hover:underline">Import more</Link>.</EmptyState> : (
          <div className="panel p-5">
            <label className="mb-4 block max-w-md text-xs text-ink-300">Baseline
              <select value={other.experiment_id} onChange={(e) => setOtherId(e.target.value)} className="mt-1 w-full rounded-md border border-ink-600 bg-ink-900 px-2.5 py-2 font-mono text-[12px] text-ink-50">
                {items.filter((i) => i.exp.experiment_id !== exp.experiment_id).map((i) => <option key={i.exp.experiment_id} value={i.exp.experiment_id}>{i.exp.experiment_id}</option>)}
              </select>
            </label>
            <CompareTable baseline={other} candidate={exp} />
          </div>
        )}
      </Section>
    </>
  );
}

export default function Results() {
  const { id } = useParams();
  const { items, ready } = useResults();
  if (!ready) return <><Skeleton className="h-8 w-80" /><Skeleton className="mt-6 h-40" /></>;
  const found = items.find((i) => i.exp.experiment_id === id)?.exp;
  if (!found) {
    return (
      <EmptyState title="This experiment is not loaded in this browser" action={<ButtonLink to="/dashboard/experiments" variant="secondary" size="sm">Go to Experiments</ButtonLink>}>
        Results come from result files imported into this browser. <span className="font-mono text-ink-100">{id}</span> has not been imported here, or it was removed.
      </EmptyState>
    );
  }
  return <Detail exp={found} />;
}
