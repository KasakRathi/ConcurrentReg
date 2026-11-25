import { ArrowRight, Check, Database, Loader2, Play, RotateCcw, ScanSearch, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useDemoInfo, useDemoRun, useDemoState, useVerification } from "@/hooks/demo";
import { useMonitor } from "@/hooks/monitor";
import { useResults } from "@/hooks/results-store";
import { LiveChart } from "@/components/charts/LiveChart";
import { CompareTable } from "@/components/dashboard/CompareTable";
import { Metric, MetricGrid, PageHeader } from "@/components/dashboard/parts";
import { DbBadge, InvariantList, OutcomeTimeline, SeatRow, Step, TestStream } from "@/components/demo/parts";
import { Button, ButtonLink } from "@/components/ui/Button";
import { CodeBlock } from "@/components/ui/CodeBlock";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { DemoError, getRegistrations, resetData, setServerSettings, type RegistrationRow } from "@/lib/demoApi";
import { fmtInt, fmtMs, fmtNum } from "@/lib/format";
import { SCENARIOS, TALK_TRACK } from "@/lib/scenarios";
import { COLORS } from "@/lib/theme";

function Slider({ label, value, min, max, onChange, disabled }: { label: string; value: number; min: number; max: number; onChange: (n: number) => void; disabled?: boolean }) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between text-[12.5px] text-ink-300"><span>{label}</span><span className="tabular font-mono text-ink-50">{value}</span></span>
      <input type="range" min={min} max={max} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} className="mt-2 h-1 w-full cursor-pointer appearance-none rounded-full bg-ink-600 accent-[#6ee7b7] disabled:opacity-40" />
    </label>
  );
}

export default function Demo() {
  const navigate = useNavigate();
  const { info, error: infoError, refresh: refreshInfo } = useDemoInfo();
  const enabled = !!info?.controls_enabled;
  const run = useDemoRun();
  const { state, error: stateError, setState } = useDemoState(enabled, run.running);
  const verification = useVerification();
  const monitor = useMonitor();
  const { items } = useResults();

  const [scenarioId, setScenarioId] = useState("race");
  const [seed, setSeed] = useState<number | null>(null);
  const [resetFirst, setResetFirst] = useState(true);
  const [settings, setSettings] = useState({ queue_capacity: 16, worker_count: 4, db_semaphore_permits: 2 });
  const [applying, setApplying] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [rows, setRows] = useState<RegistrationRow[] | null>(null);
  const [showRows, setShowRows] = useState(false);
  const scenario = SCENARIOS.find((s) => s.id === scenarioId)!;

  // keep the settings sliders in step with what the server really runs
  useEffect(() => { if (info) setSettings(info.os_layer); }, [info?.os_layer.queue_capacity, info?.os_layer.worker_count, info?.os_layer.db_semaphore_permits]); // eslint-disable-line react-hooks/exhaustive-deps
  // sample the live counters once a second while this page is open
  useEffect(() => {
    const previous = monitor.intervalMs;
    monitor.setIntervalMs(1000);
    return () => monitor.setIntervalMs(previous);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // show the stored rows whenever asked, and again when a run finishes
  useEffect(() => {
    if (!enabled || !showRows) return;
    getRegistrations().then(setRows, () => setRows(null));
  }, [enabled, showRows, run.job?.status, state?.totals.registrations]);

  const busy = run.running || verification.running;
  const settingsChanged = !!info && (settings.queue_capacity !== info.os_layer.queue_capacity || settings.worker_count !== info.os_layer.worker_count || settings.db_semaphore_permits !== info.os_layer.db_semaphore_permits);
  const runSamples = useMemo(() => {
    if (!run.job) return [];
    const from = Date.parse(run.job.started_at) - 3000;
    return monitor.samples.filter((s) => s.t >= from);
  }, [monitor.samples, run.job]);
  const compare = useMemo(() => {
    const withServer = items.filter((i) => i.exp.server);
    return withServer.length >= 2 ? { baseline: withServer[1].exp, candidate: withServer[0].exp } : null;
  }, [items]);

  const applySettings = async () => {
    setApplying(true);
    setSettingsError(null);
    try {
      await setServerSettings(settings);
      refreshInfo();
    } catch (e) {
      setSettingsError(e instanceof DemoError ? e.message : "Could not change the settings");
    } finally {
      setApplying(false);
    }
  };
  const doReset = async () => {
    setResetting(true);
    try {
      setState(await resetData());
      run.clear();
    } catch (e) {
      setSettingsError(e instanceof DemoError ? e.message : "Reset failed");
    } finally {
      setResetting(false);
    }
  };

  const header = (
    <PageHeader
      title="Live demo"
      description="Drive the real system from here: configure the server, run a workload against it, read the evidence in the database, and run the project's own tests. Every number on this page comes from the running backend."
      actions={<SourceBadge source={enabled ? "live" : "unavailable"} label={enabled ? "Connected to the backend" : "Controls off"} />}
    />
  );

  if (!info && !infoError) return <>{header}<div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-64" /></div></>;
  if (infoError && !info) {
    return (
      <>
        {header}
        <ErrorState title={infoError.kind === "unreachable" ? "The backend is not reachable" : "The backend did not answer as expected"} action={<Button size="sm" variant="secondary" onClick={refreshInfo}>Retry</Button>}>
          <p>{infoError.message}</p>
          <p className="mt-2 text-ink-300">One command starts the database, the backend and this dashboard:</p>
          <CodeBlock className="mt-3 w-full" title="terminal" code="./scripts/start_demo.sh" />
        </ErrorState>
      </>
    );
  }
  if (info && !info.controls_enabled) {
    return (
      <>
        {header}
        <EmptyState title="The server's demo controls are switched off" icon={<ShieldCheck className="size-6" />}>
          Resetting the database and running the test suite are deliberately unavailable unless the server is started with <code className="text-ink-100">CREG_DEMO_CONTROLS=1</code>.
          <CodeBlock className="mt-4 w-full text-left" title="start in demo mode" code="./scripts/start_demo.sh" />
        </EmptyState>
      </>
    );
  }
  const db = info!.database;
  const allSeatsFull = state ? state.sections.every((s) => s.available_seats === 0) : false;

  return (
    <>
      {header}
      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div>
          {/* ------------------------------------------------------------ 1 */}
          <Step n={1} title="The system" status="done" aside={<SourceBadge source="live" />}>
            <div className="space-y-3">
              <DbBadge db={db} />
              <div className="panel p-5">
                <p className="eyebrow">Server settings</p>
                <p className="mt-1 text-[12.5px] leading-5 text-ink-300">Normally fixed at start-up. In demo mode you can swap the queue, worker pool and semaphore without restarting, to compare settings with the same workload.</p>
                <div className="mt-4 grid gap-5 sm:grid-cols-3">
                  <Slider label="Queue capacity" value={settings.queue_capacity} min={1} max={64} disabled={busy} onChange={(n) => setSettings((s) => ({ ...s, queue_capacity: n }))} />
                  <Slider label="Worker threads" value={settings.worker_count} min={1} max={16} disabled={busy} onChange={(n) => setSettings((s) => ({ ...s, worker_count: n }))} />
                  <Slider label="DB semaphore permits" value={settings.db_semaphore_permits} min={1} max={16} disabled={busy} onChange={(n) => setSettings((s) => ({ ...s, db_semaphore_permits: n }))} />
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <Button size="sm" variant={settingsChanged ? "primary" : "secondary"} disabled={!settingsChanged || busy || applying} onClick={applySettings}>{applying ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />} Apply to the server</Button>
                  <span className="text-[12px] text-ink-400">Running now: queue {info!.os_layer.queue_capacity} · workers {info!.os_layer.worker_count} · permits {info!.os_layer.db_semaphore_permits}. Experimental parameters, not recommendations.</span>
                </div>
                {settingsError && <p className="mt-3 text-[13px] text-rose">{settingsError}</p>}
              </div>
            </div>
          </Step>

          {/* ------------------------------------------------------------ 2 */}
          <Step n={2} title="The data and its correctness rules" status={state?.all_ok ? "done" : "active"} aside={<div className="flex items-center gap-2"><SourceBadge source="live" label="Live SQL" /><Button size="sm" variant="secondary" disabled={busy || resetting} onClick={doReset}>{resetting ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />} Reset data</Button></div>}>
            {!state && !stateError && <Skeleton className="h-40" />}
            {stateError && !state && <ErrorState title="Could not read the database state">{stateError.message}</ErrorState>}
            {state && (
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-3">
                  {state.sections.map((s) => <SeatRow key={s.id} s={s} />)}
                  <p className="text-[12.5px] text-ink-400">{state.totals.students} students (STU001 to STU{String(state.totals.students).padStart(3, "0")}) · {state.totals.registrations} registrations stored · read at {new Date(state.taken_at).toLocaleTimeString("en-GB")}</p>
                </div>
                <div>
                  <InvariantList items={state.invariants} />
                  <button onClick={() => setShowRows((v) => !v)} className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-ink-200 hover:text-mint" aria-expanded={showRows}><Database className="size-3.5" /> {showRows ? "Hide" : "Show"} the stored registration rows</button>
                </div>
                {showRows && (
                  <div className="panel scroll-x lg:col-span-2">
                    {!rows || rows.length === 0 ? <p className="px-4 py-3 text-[13px] text-ink-300">{rows ? "The registrations table is empty." : "Loading…"}</p> : (
                      <table className="w-full min-w-[480px] text-left text-[12.5px]"><thead><tr className="border-b border-ink-700 text-ink-300"><th className="px-4 py-2 font-medium">id</th><th className="px-3 py-2 font-medium">student</th><th className="px-3 py-2 font-medium">course</th><th className="px-3 py-2 font-medium">status</th><th className="px-4 py-2 font-medium">registered at</th></tr></thead>
                        <tbody className="font-mono">{rows.map((r) => <tr key={r.id} className="border-b border-ink-800 last:border-0"><td className="px-4 py-1.5 text-ink-400">{r.id}</td><td className="px-3 py-1.5 text-ink-50">{r.student}</td><td className="px-3 py-1.5 text-ink-100">{r.course}</td><td className="px-3 py-1.5 text-mint">{r.status}</td><td className="px-4 py-1.5 text-ink-300">{r.registered_at.slice(11)}</td></tr>)}</tbody></table>
                    )}
                  </div>
                )}
              </div>
            )}
          </Step>

          {/* ------------------------------------------------------------ 3 */}
          <Step n={3} title="Run an experiment" status={run.running ? "active" : run.job?.status === "done" ? "done" : "idle"} aside={<SourceBadge source="live" label="Real HTTP requests" />}>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" role="radiogroup" aria-label="Scenario">
              {SCENARIOS.map((s) => (
                <button key={s.id} role="radio" aria-checked={scenarioId === s.id} disabled={busy} onClick={() => setScenarioId(s.id)} className={cn("panel p-4 text-left transition disabled:opacity-60", scenarioId === s.id ? "!border-mint/50 ring-1 ring-mint/30" : "hover:!border-ink-500")}>
                  <span className="flex items-center justify-between"><span className="text-[14.5px] font-medium text-ink-50">{s.title}</span><span className="rounded-full border border-ink-600 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-300">{s.tag}</span></span>
                  <span className="mt-1.5 block text-[13px] leading-5 text-ink-200">{s.blurb}</span>
                  <span className="mt-2 block font-mono text-[11px] text-ink-400">{s.duration}</span>
                </button>
              ))}
            </div>

            <div className="panel mt-3 p-5">
              <dl className="grid gap-4 text-[13px] sm:grid-cols-2">
                <div><dt className="eyebrow">Watch for</dt><dd className="mt-1 leading-5 text-ink-100">{scenario.watch}</dd></div>
                <div><dt className="eyebrow">Holds whatever happens</dt><dd className="mt-1 leading-5 text-ink-100">{scenario.guarantee}</dd></div>
              </dl>
              <div className="mt-5 flex flex-wrap items-end gap-x-6 gap-y-3 border-t border-ink-700 pt-4">
                <label className="block text-xs text-ink-300">Seed
                  <input type="number" min={0} value={seed ?? (scenario.request.seed as number)} disabled={busy} onChange={(e) => setSeed(e.target.value === "" ? null : Math.max(0, Math.floor(Number(e.target.value))))} className="mt-1 block w-24 rounded-md border border-ink-600 bg-ink-900 px-2.5 py-1.5 font-mono text-[13px] text-ink-50" />
                </label>
                <label className="flex items-center gap-2 pb-1.5 text-[13px] text-ink-200"><input type="checkbox" checked={resetFirst} disabled={busy} onChange={(e) => setResetFirst(e.target.checked)} className="accent-[#6ee7b7]" /> Reset the data first <span className="text-ink-400">(needed for the database cross-check)</span></label>
                <Button variant="mint" className="ml-auto" disabled={busy || run.starting} onClick={() => void run.start({ ...scenario.request, seed: seed ?? scenario.request.seed, reset_first: resetFirst })}>
                  {run.running || run.starting ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} {run.running ? "Running…" : "Run scenario"}
                </Button>
              </div>
            </div>

            {run.error && <ErrorState className="mt-3" title={run.error.kind === "busy" ? "The server is busy" : "The run could not start"}>{run.error.message}</ErrorState>}

            {run.job && (
              <div className="panel mt-3 p-5" aria-live="polite">
                <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
                  <span className="flex items-center gap-2 text-ink-50">{run.running ? <Loader2 className="size-4 animate-spin text-sky" /> : run.job.status === "done" ? <Check className="size-4 text-mint" /> : <TriangleAlert className="size-4 text-rose" />}{run.running ? "Sending requests to the server…" : run.job.status === "done" ? "Run finished" : "Run failed"}</span>
                  <span className="tabular font-mono text-ink-300">{fmtInt(run.job.progress.responses_seen)} / {fmtInt(run.job.progress.planned_requests)} answered · {fmtNum(run.job.progress.elapsed_s, 1)} s</span>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink-700"><div className="h-full rounded-full bg-mint transition-all duration-300" style={{ width: `${Math.round(run.job.progress.fraction * 100)}%` }} /></div>
                <p className="mt-2 text-[11.5px] text-ink-400">{run.job.progress.note}</p>
                {run.job.error && <p className="mt-3 text-[13px] text-rose">{run.job.error}</p>}
                {monitor.status && runSamples.length > 1 && (
                  <div className="mt-4">
                    <LiveChart samples={runSamples} step height={150} series={[{ key: "depth", label: "Queue depth", color: COLORS.amber }, { key: "activeWorkers", label: "Active workers", color: COLORS.sky }, { key: "semHolders", label: "Permits held", color: COLORS.violet }]} referenceY={monitor.status.queue.capacity} referenceLabel={`queue capacity ${monitor.status.queue.capacity}`} />
                    <p className="mt-1 text-[11.5px] text-ink-400">Sampled once a second from GET /os-layer/status. A very short run can finish between two samples.</p>
                  </div>
                )}
              </div>
            )}
          </Step>

          {/* ------------------------------------------------------------ 4 */}
          <Step n={4} title="The evidence" status={run.experiment ? "done" : "idle"} aside={run.experiment ? <SourceBadge source="file" label="Result file from the server" /> : undefined}>
            {!run.job || run.job.status === "running" ? (
              <EmptyState title="Run a scenario to see its evidence" icon={<ScanSearch className="size-6" />}>The run's result file, the database cross-check and the answer-by-answer timeline appear here.</EmptyState>
            ) : run.job.status === "failed" ? (
              <ErrorState title="The run failed">{run.job.error}</ErrorState>
            ) : (
              <div className="space-y-3">
                {run.job.db_check && (
                  <div className={cn("rounded-xl border px-4 py-3", run.job.db_check.match === false || !run.job.db_check.invariants_ok ? "border-rose/40 bg-rose/[0.06]" : "border-mint/30 bg-mint/[0.05]")}>
                    <p className="flex items-center gap-2 text-[15px] font-medium text-ink-50">
                      {run.job.db_check.match === false || !run.job.db_check.invariants_ok ? <TriangleAlert className="size-4 text-rose" /> : <ShieldCheck className="size-4 text-mint" />}
                      {run.job.db_check.match === null ? "Database checked (counts not compared: the data was not reset first)" : run.job.db_check.match ? "The database agrees with the client" : "MISMATCH between the client and the database"}
                    </p>
                    <p className="mt-1 text-[13px] leading-5 text-ink-200">
                      The client was told <b className="font-mono text-ink-50">{run.job.db_check.successes_reported_by_client}</b> registrations succeeded; MySQL stores <b className="font-mono text-ink-50">{run.job.db_check.registrations_in_db}</b>. All four correctness rules {run.job.db_check.invariants_ok ? "hold" : "do NOT hold"} after the run.
                    </p>
                  </div>
                )}
                {run.job.summary && (
                  <MetricGrid cols={5}>
                    <Metric label="Registered" value={fmtInt(run.job.summary.category_counts.SUCCESS ?? 0)} tone="mint" sub="HTTP 201" />
                    <Metric label="Course full" value={fmtInt(run.job.summary.category_counts.COURSE_FULL ?? 0)} tone="amber" sub="no seats left" />
                    <Metric label="Duplicate" value={fmtInt(run.job.summary.category_counts.DUPLICATE ?? 0)} tone="violet" sub="already registered" />
                    <Metric label="Queue full" value={fmtInt(run.job.summary.category_counts.QUEUE_FULL ?? 0)} tone="rose" sub="refused at once" />
                    <Metric label="Latency p95" value={fmtMs(run.job.summary.latency_ms?.p95)} sub={`${fmtNum(run.job.summary.completed_requests_per_second, 0)} req/s completed`} />
                  </MetricGrid>
                )}
                {run.experiment ? (
                  <div className="panel p-5">
                    <p className="eyebrow mb-3">Every request, in the order the server answered it</p>
                    <OutcomeTimeline exp={run.experiment} />
                    {run.experiment.summary.open_loop && !run.experiment.summary.open_loop.valid_open_loop && <p className="mt-3 text-[12.5px] text-amber">This run is flagged invalid as open-loop evidence: {run.experiment.summary.open_loop.invalid_reasons.join("; ")}.</p>}
                  </div>
                ) : <Skeleton className="h-24" />}
                <div className="flex flex-wrap gap-2">
                  {run.experiment && <Button variant="secondary" size="sm" onClick={() => navigate(`/dashboard/results/${encodeURIComponent(run.experiment!.experiment_id)}`)}>Open the full results <ArrowRight className="size-3.5" /></Button>}
                  <ButtonLink to="/dashboard/experiments" variant="ghost" size="sm">All experiments</ButtonLink>
                </div>
                {compare && (
                  <div className="panel p-5">
                    <p className="text-[14px] font-medium text-ink-50">Previous run versus this one</p>
                    <p className="mt-1 mb-4 text-[12.5px] text-ink-300">Change the server settings in step 1 and run the same scenario again to compare. The settings used by each run are recorded in its result file.</p>
                    <CompareTable baseline={compare.baseline} candidate={compare.candidate} />
                  </div>
                )}
              </div>
            )}
          </Step>

          {/* ------------------------------------------------------------ 5 */}
          <Step n={5} title="Run the project's tests" status={verification.snap.status === "done" && !verification.snap.error ? "done" : verification.running ? "active" : "idle"} aside={<SourceBadge source="live" label="Real pytest run" />}>
            <div className="panel p-5">
              <p className="text-[13.5px] leading-6 text-ink-200">Runs the repository's own <code className="text-ink-50">pytest</code> suite on the server against a separate test database{info!.tests.dialect ? <> (<b className="uppercase text-ink-50">{info!.tests.dialect}</b>)</> : null}, never the demo data. Results stream in as each test finishes.</p>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <Button variant="primary" disabled={busy || !info!.tests.available} onClick={() => void verification.start()}>{verification.running ? <Loader2 className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />} {verification.running ? "Running…" : "Run the test suite"}</Button>
                {!info!.tests.available && <span className="text-[12.5px] text-amber">{info!.tests.reason}</span>}
              </div>
              {verification.error && <p className="mt-3 text-[13px] text-rose">{verification.error.message}</p>}
            </div>
            {verification.snap.status !== "none" && <div className="mt-3"><TestStream snap={verification.snap} /></div>}
          </Step>
        </div>

        {/* presenter notes */}
        <aside className="xl:sticky xl:top-20 xl:self-start" aria-label="Presenter notes">
          <details className="panel p-4 xl:open" open>
            <summary className="cursor-pointer text-[14px] font-medium text-ink-50">Presenter notes</summary>
            <ol className="mt-3 space-y-4">
              {TALK_TRACK.map((t) => <li key={t.step}><p className="font-mono text-[11px] uppercase tracking-wider text-mint">{t.step}</p><p className="mt-1 text-[12.5px] leading-5 text-ink-200">{t.say}</p></li>)}
            </ol>
            <p className="mt-5 border-t border-ink-700 pt-3 text-[11.5px] leading-4 text-ink-400">Workloads are synthetic and the defaults are demonstration values. A single run varies with thread scheduling; the invariants, not the timings, are the claim.</p>
            <Link to="/dashboard/architecture" className="mt-3 inline-block text-[12.5px] text-mint hover:underline">Open the architecture explorer</Link>
          </details>
        </aside>
      </div>
      {allSeatsFull && <p className="sr-only" role="status">All seats are taken.</p>}
    </>
  );
}
