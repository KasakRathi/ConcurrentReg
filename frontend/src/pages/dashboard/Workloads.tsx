import { Link, useNavigate } from "react-router-dom";
import { Loader2, Play } from "lucide-react";
import { useDemoInfo, useDemoRun } from "@/hooks/demo";
import { configToRunRequest } from "@/lib/demoApi";
import { fmtInt } from "@/lib/format";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartFrame, ChartTooltip, axisProps, gridProps } from "@/components/charts/common";
import { PageHeader, Section } from "@/components/dashboard/parts";
import { Button } from "@/components/ui/Button";
import { CodeBlock } from "@/components/ui/CodeBlock";
import { cn } from "@/lib/cn";
import { buildCommand, buildServerCommand, DEFAULT_CONFIG } from "@/lib/command";
import { arrivalOffsets, LIMITS, phasePlan, plannedRequestCount, scheduleRateBins, validateConfig } from "@/lib/schedule";
import { COLORS } from "@/lib/theme";
import type { WorkloadConfig } from "@/lib/types";

const PRESETS: { name: string; patch: Partial<WorkloadConfig> }[] = [
  { name: "Steady", patch: { arrival_model: "open", pattern: "steady", rate: 10, request_count: 100, contention: "independent" } },
  { name: "Burst", patch: { arrival_model: "open", pattern: "burst", request_count: 50, contention: "hot" } },
  { name: "Ramp-up", patch: { arrival_model: "open", pattern: "ramp", rate: 40, ramp_stages: 4, request_count: 160, contention: "mixed", section_ids: [1, 2, 3], hot_section_count: 1 } },
  { name: "Recovery (phases)", patch: { arrival_model: "open", pattern: "phases", phases: [[10, 5], [100, 2], [10, 10]], contention: "hot" } },
  { name: "Closed loop", patch: { arrival_model: "closed", virtual_users: 10, think_time_min_s: 0.1, think_time_max_s: 0.3, request_count: 100, contention: "hot" } },
];

function phasesToText(p: [number, number][]) { return p.map(([r, d]) => `${r}:${d}`).join(","); }
function parsePhases(text: string): [number, number][] | null {
  try {
    const parsed = text.split(",").map((part) => { const [r, d] = part.split(":"); return [Number(r), Number(d)] as [number, number]; });
    return parsed.every(([r, d]) => Number.isFinite(r) && Number.isFinite(d)) ? parsed : null;
  } catch { return null; }
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <label className="block"><span className="text-xs font-medium text-ink-200">{label}</span>{children}{hint && <span className="mt-1 block text-[11px] leading-snug text-ink-400">{hint}</span>}</label>;
}
const inputCls = "mt-1 w-full rounded-md border border-ink-600 bg-ink-900 px-2.5 py-2 font-mono text-[13px] text-ink-50 placeholder:text-ink-500 focus:border-mint";

function Num({ label, value, onChange, hint, step = 1, min }: { label: string; value: number; onChange: (n: number) => void; hint?: string; step?: number; min?: number }) {
  return <Field label={label} hint={hint}><input type="number" className={inputCls} value={Number.isFinite(value) ? value : ""} step={step} min={min} onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))} /></Field>;
}

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: readonly T[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-ink-600 p-0.5">
      {options.map((o) => <button key={o} onClick={() => onChange(o)} aria-pressed={value === o} className={cn("rounded-md px-3 py-1.5 text-[13px] capitalize transition", value === o ? "bg-ink-50 text-ink-950" : "text-ink-300 hover:text-ink-50")}>{o}</button>)}
    </div>
  );
}

/** Appears only when the server reports its demo controls are on: runs THIS configuration against the live backend. */
function RunNow({ config, valid }: { config: WorkloadConfig; valid: boolean }) {
  const { info } = useDemoInfo();
  const run = useDemoRun();
  const navigate = useNavigate();
  if (!info?.controls_enabled) return null;
  return (
    <Section title="Run it now" source="live" sourceLabel="Live backend" note="Sends this configuration to the running server, resets the data first, and saves the generator's result file. Sections and students must exist in the database (the seed has 2 sections and 10 students).">
      <div className="panel p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="mint" size="sm" disabled={!valid || run.running || run.starting} onClick={() => void run.start(configToRunRequest(config))}>{run.running || run.starting ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} Run on the backend</Button>
          {run.job && <span className="tabular font-mono text-[12.5px] text-ink-200">{fmtInt(run.job.progress.responses_seen)} / {fmtInt(run.job.progress.planned_requests)} answered</span>}
        </div>
        {run.error && <p className="mt-3 text-[13px] text-rose">{run.error.message}</p>}
        {run.job?.status === "failed" && <p className="mt-3 text-[13px] text-rose">{run.job.error}</p>}
        {run.job?.status === "done" && run.job.summary && (
          <div className="mt-3 text-[13px] text-ink-100">
            <p>Done: <b className="font-mono text-mint">{run.job.summary.successful_requests}</b> of {run.job.summary.total_requests} registered{run.job.db_check?.match ? <> · the database holds the same number ✓</> : null}.</p>
            {run.experiment && <Button className="mt-2" size="sm" variant="secondary" onClick={() => navigate(`/dashboard/results/${encodeURIComponent(run.experiment!.experiment_id)}`)}>Open the full results</Button>}
          </div>
        )}
      </div>
    </Section>
  );
}

export default function Workloads() {
  const [c, setC] = useState<WorkloadConfig>({ ...DEFAULT_CONFIG, pattern: "phases", phases: [[10, 5], [100, 2], [10, 10]] });
  const [phaseText, setPhaseText] = useState("10:5,100:2,10:10");
  const [sectionsText, setSectionsText] = useState("1,2");
  const [server, setServer] = useState({ q: 16, w: 4, p: 2 });
  const patch = (p: Partial<WorkloadConfig>) => setC((cur) => ({ ...cur, ...p }));

  const problems = useMemo(() => validateConfig(c), [c]);
  const open = c.arrival_model === "open";
  const offsets = useMemo(() => (open && problems.length === 0 ? arrivalOffsets(c) : []), [c, open, problems.length]);
  const count = problems.length === 0 ? plannedRequestCount(c) : null;
  const span = offsets.length ? Math.max(...offsets) : 0;
  const binSeconds = span <= 5 ? 0.25 : span <= 30 ? 1 : span <= 120 ? 2 : 5;
  const bins = useMemo(() => scheduleRateBins(offsets, binSeconds), [offsets, binSeconds]);
  const command = problems.length === 0 ? buildCommand(c) : "# fix the problems listed above to get a command";

  return (
    <>
      <PageHeader title="Workloads" description="Configure what the workload generator will send. The browser cannot start a run (the backend has no endpoint for that), so this page validates the settings, previews the schedule and writes the exact terminal command." />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div>
          <Section title="Presets" source="schematic" note="Starting points built from the generator's own options. Values are demonstration values, not research parameters.">
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((p) => (
                <Button key={p.name} size="sm" variant="secondary" onClick={() => {
                  const next = { ...DEFAULT_CONFIG, ...p.patch };
                  setC(next); setPhaseText(phasesToText(next.phases)); setSectionsText(next.section_ids.join(","));
                }}>{p.name}</Button>
              ))}
            </div>
          </Section>

          <Section title="Arrival model">
            <div className="panel space-y-5 p-5">
              <div className="flex flex-wrap items-center gap-4">
                <Seg label="Arrival model" value={c.arrival_model} options={["open", "closed"] as const} onChange={(v) => patch({ arrival_model: v, pattern: v === "closed" && c.pattern === "phases" ? "burst" : c.pattern })} />
                <p className="max-w-sm text-xs leading-relaxed text-ink-400">{open ? "Open loop: every request has an intended arrival time, fixed in advance. Responses never change it." : "Closed loop: N virtual users, each thinks, sends, waits for the response, then repeats. Arrivals depend on the server's speed."}</p>
              </div>
              {open ? (
                <>
                  <Seg label="Pattern" value={c.pattern} options={["steady", "burst", "ramp", "phases"] as const} onChange={(v) => patch({ pattern: v })} />
                  <div className="grid gap-4 sm:grid-cols-2">
                    {c.pattern === "phases" ? (
                      <div className="sm:col-span-2">
                        <Field label="Phases (RATE:DURATION, comma separated)" hint="Example: 10:5,100:2,10:10 = 10/s for 5 s, 100/s for 2 s, then 10/s for 10 s. The request count comes from the phases."><input className={inputCls} value={phaseText} onChange={(e) => { setPhaseText(e.target.value); const p = parsePhases(e.target.value); patch({ phases: p ?? [] }); }} /></Field>
                      </div>
                    ) : <Num label="Requests" value={c.request_count} onChange={(n) => patch({ request_count: n })} hint={`1 to ${LIMITS.maxRequests.toLocaleString()}`} />}
                    {(c.pattern === "steady" || c.pattern === "ramp") && <Num label={c.pattern === "ramp" ? "Final-stage rate (req/s)" : "Rate (req/s)"} value={c.rate} step={0.5} onChange={(n) => patch({ rate: n })} />}
                    {c.pattern === "ramp" && <Num label="Ramp stages" value={c.ramp_stages} onChange={(n) => patch({ ramp_stages: n })} />}
                    <Num label="In-flight cap (--concurrency)" value={c.concurrency} onChange={(n) => patch({ concurrency: n })} hint={`1 to ${LIMITS.maxInFlight}. Each in-flight request is a client thread and a connection.`} />
                    <Num label="Lateness tolerance (ms)" value={c.lateness_tolerance_ms} onChange={(n) => patch({ lateness_tolerance_ms: n })} hint="A request sent later than this makes the run invalid for open-loop use." />
                  </div>
                </>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Num label="Requests" value={c.request_count} onChange={(n) => patch({ request_count: n })} />
                  <Num label="Virtual users" value={c.virtual_users} onChange={(n) => patch({ virtual_users: n })} hint={`1 to ${LIMITS.maxVirtualUsers}`} />
                  <Num label="Think time min (s)" value={c.think_time_min_s} step={0.05} min={0} onChange={(n) => patch({ think_time_min_s: n })} />
                  <Num label="Think time max (s)" value={c.think_time_max_s} step={0.05} min={0} onChange={(n) => patch({ think_time_max_s: n })} hint="Equal to min means a fixed think time." />
                </div>
              )}
            </div>
          </Section>

          <Section title="Targets and reproducibility">
            <div className="panel space-y-5 p-5">
              <Seg label="Contention" value={c.contention} options={["hot", "independent", "mixed"] as const} onChange={(v) => patch({ contention: v })} />
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Section ids" hint="Comma separated. The first N are the hot sections."><input className={inputCls} value={sectionsText} onChange={(e) => { setSectionsText(e.target.value); patch({ section_ids: e.target.value.split(",").map((s) => Number(s.trim())).filter((n) => e.target.value.trim() !== "" && Number.isFinite(n)) }); }} /></Field>
                <Num label="Hot sections" value={c.hot_section_count} onChange={(n) => patch({ hot_section_count: n })} />
                {c.contention === "mixed" && <Num label="Hot fraction (0 to 1)" value={c.hot_fraction} step={0.05} onChange={(n) => patch({ hot_fraction: n })} />}
                <Num label="Duplicate fraction (0 to 1)" value={c.duplicate_fraction} step={0.05} onChange={(n) => patch({ duplicate_fraction: n })} hint="Share of requests that repeat an earlier student and section." />
                <Num label="Students" value={c.student_count} onChange={(n) => patch({ student_count: n })} hint="STU001 to STUnnn must exist in the database. The seed data has 10." />
                <Num label="Seed" value={c.seed} onChange={(n) => patch({ seed: n })} hint="The same seed and settings give the same schedule and targets. Timing is not reproducible." />
                <Num label="Request timeout (s)" value={c.timeout_seconds} step={0.5} onChange={(n) => patch({ timeout_seconds: n })} />
              </div>
            </div>
          </Section>
        </div>

        <div className="min-w-0 xl:sticky xl:top-20 xl:self-start">
          <Section title="Validation" source="schematic" sourceLabel="Mirrors the generator">
            {problems.length === 0 ? <p className="rounded-lg border border-mint/25 bg-mint/[0.05] px-4 py-3 text-[13px] text-ink-100">The generator's validation would accept this configuration{count != null ? <> and send <b className="font-mono">{count.toLocaleString()}</b> requests</> : null}.</p> : (
              <ul className="space-y-1.5 rounded-lg border border-rose/30 bg-rose/[0.05] px-4 py-3 text-[13px] text-ink-100" role="alert">{problems.map((p) => <li key={p}>• {p}</li>)}</ul>
            )}
          </Section>

          <RunNow config={c} valid={problems.length === 0} />

          {open && (
            <Section title="Schedule preview" source="schematic" sourceLabel="Computed from settings">
              {offsets.length === 0 ? <p className="text-[13px] text-ink-400">No schedule until the settings are valid.</p> : (
                <ChartFrame title="Intended arrival rate (req/s)" subtitle={`${offsets.length.toLocaleString()} requests over ${span.toFixed(2)} s, in ${binSeconds} s bins. The generator's own arrival rules, ported and checked against its output.`}>
                  <div style={{ height: 200 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={bins} margin={{ top: 6, right: 6, left: -12, bottom: 0 }} barCategoryGap={1}>
                        <CartesianGrid {...gridProps} />
                        <XAxis dataKey="t" {...axisProps} tickFormatter={(v: number) => `${v}s`} minTickGap={24} />
                        <YAxis {...axisProps} width={44} />
                        <Tooltip content={<ChartTooltip labelFormat={(v) => `from ${v} s`} valueFormat={(v) => `${v.toFixed(1)} /s`} />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                        <Bar dataKey="rate" name="Intended rate" fill={COLORS.sky} radius={[2, 2, 0, 0]} isAnimationActive={false} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  {c.pattern === "phases" && c.phases.length > 0 && (
                    <div className="scroll-x mt-3"><table className="w-full min-w-[420px] text-left text-[12px]"><thead><tr className="text-ink-400">{["Phase", "Rate", "Duration", "Window", "Requests"].map((h) => <th key={h} className="py-1 pr-3 font-medium">{h}</th>)}</tr></thead><tbody className="font-mono text-ink-100">{phasePlan(c.phases).map((p) => <tr key={p.index}><td className="py-1 pr-3">{p.index + 1}</td><td className="pr-3">{p.rate_per_s}/s</td><td className="pr-3">{p.duration_s}s</td><td className="pr-3">[{p.start_s}, {p.end_s})</td><td>{p.requests}</td></tr>)}</tbody></table></div>
                  )}
                </ChartFrame>
              )}
            </Section>
          )}

          <Section title="Run it" source="schematic" sourceLabel="Terminal command" note="Re-seed the database before each run you want to compare. The command contains only flags the generator defines (checked by parsing it back with the generator's own argument parser).">
            <CodeBlock title="1 · reset data" code=".venv/bin/python -m app.seed" />
            <div className="mt-3 rounded-lg border border-ink-700 bg-ink-900/60 p-4">
              <p className="eyebrow">Server settings (environment variables, fixed while the server runs)</p>
              <div className="mt-2 grid grid-cols-3 gap-3">
                <Num label="Queue capacity" value={server.q} onChange={(n) => setServer((s) => ({ ...s, q: n }))} min={1} />
                <Num label="Workers" value={server.w} onChange={(n) => setServer((s) => ({ ...s, w: n }))} min={1} />
                <Num label="DB permits" value={server.p} onChange={(n) => setServer((s) => ({ ...s, p: n }))} min={1} />
              </div>
              <p className="mt-2 text-[11px] text-ink-400">Development defaults are 16, 4 and 2. They are experimental parameters, not recommendations.</p>
            </div>
            <CodeBlock className="mt-3" title="2 · start the server" code={[server.q, server.w, server.p].every((n) => Number.isInteger(n) && n >= 1) ? buildServerCommand(server.q, server.w, server.p) : "# queue capacity, workers and permits must be whole numbers of at least 1"} />
            <CodeBlock className="mt-3" title="3 · run the workload" code={command} />
            <p className="mt-3 text-xs text-ink-400">The run writes <code className="text-ink-200">results/&lt;experiment-id&gt;.json</code>. Import it on the <Link className="text-mint hover:underline" to="/dashboard/experiments">Experiments</Link> page.</p>
          </Section>

          <Section title="Not supported">
            <ul className="space-y-1.5 text-[13px] text-ink-300">
              <li>• Starting a run from the browser: the API has no endpoint for it.</li>
              <li>• Random (Poisson) arrivals, dataset scaling and a server-side experiment runner: the generator does not implement them.</li>
              <li>• Retries and learned or AI policies: not implemented. Admission control exists only as the optional, off-by-default IASL layer, which this page does not configure.</li>
            </ul>
          </Section>
        </div>
      </div>
    </>
  );
}
