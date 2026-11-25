import { Pause, Play, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { ControllerFacts } from "@/components/iasl/ControllerFacts";
import { DecisionLog } from "@/components/iasl/DecisionLog";
import { Gate } from "@/components/iasl/Gate";
import { IaslChart } from "@/components/iasl/IaslChart";
import { IaslOffState } from "@/components/iasl/IaslOffState";
import { SignalsPanel } from "@/components/iasl/SignalsPanel";
import { StateCard } from "@/components/iasl/StateCard";
import { PageHeader } from "@/components/dashboard/parts";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { Button } from "@/components/ui/Button";
import { CodeBlock } from "@/components/ui/CodeBlock";
import { EmptyState, ErrorState, Skeleton, Unavailable } from "@/components/ui/States";
import { useIasl } from "@/hooks/iasl";
import { fmtClock } from "@/lib/format";
import { signalViews } from "@/lib/iaslLogic";
import type { IaslConfigView, IaslStatus } from "@/lib/iaslTypes";

function GateOrWaiting({ status }: { status: IaslStatus }) {
  const depth = status.current_metrics?.queue_depth ?? null;
  const capacity = status.admission.capacity ?? status.current_metrics?.queue_capacity ?? null;
  const limit = status.admission.limit_in_force;
  if (depth === null || capacity === null || limit === null) {
    return (
      <section className="panel flex items-center justify-center p-5" aria-label="The gate">
        <EmptyState className="w-full border-0" title="Waiting for the first sample">The gate appears once the controller has read the queue.</EmptyState>
      </section>
    );
  }
  return <Gate depth={depth} limit={limit} capacity={capacity} minimum={status.admission.minimum} maximum={status.admission.maximum} fallback={status.fallback.active === true || status.fallback.watchdog_tripped === true} />;
}

function Settings({ config, note }: { config: IaslConfigView; note?: string }) {
  const rows = useMemo(() => Object.entries(config.settings).sort(([a], [b]) => a.localeCompare(b)), [config.settings]);
  return (
    <details className="panel group p-5">
      <summary className="flex cursor-pointer select-none flex-wrap items-center justify-between gap-2 text-sm font-medium text-ink-50">
        <span>Settings in force</span>
        <SourceBadge source="live" label="Live API" />
      </summary>
      <div className="mt-4 space-y-3">
        <p className="max-w-3xl text-[12.5px] leading-relaxed text-ink-300">
          Read-only. {config.how_to_change.charAt(0).toUpperCase() + config.how_to_change.slice(1)}.
        </p>
        {note && <p className="max-w-3xl rounded-md border border-amber/25 bg-amber/[0.05] px-3 py-2 text-[12.5px] leading-relaxed text-amber">{note}</p>}
        <div className="scroll-x rounded-md border border-ink-700">
          <table className="w-full min-w-[34rem] text-left text-[12.5px]">
            <thead className="border-b border-ink-700 text-ink-300">
              <tr><th scope="col" className="px-3 py-2 font-normal">Setting</th><th scope="col" className="px-3 py-2 font-normal">Value</th><th scope="col" className="px-3 py-2 font-normal">Environment variable</th></tr>
            </thead>
            <tbody>
              {rows.map(([key, value]) => (
                <tr key={key} className="border-t border-ink-800">
                  <td className="px-3 py-1.5 text-ink-100">{key.replace(/_/g, " ")}</td>
                  <td className="tabular px-3 py-1.5 font-mono text-ink-50">{value === null ? "automatic" : String(value)}</td>
                  <td className="px-3 py-1.5 font-mono text-ink-300">{config.environment_variables[key] ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}

export default function Iasl() {
  const { mode, error, status, metrics, history, decisions, config, lastOkAt, paused, setPaused, refresh } = useIasl();
  const signals = useMemo(() => signalViews(metrics?.analysis?.signals ?? []), [metrics?.analysis?.signals]);
  const unavailable = Object.entries(metrics?.sample?.unavailable ?? {});
  const predatesIasl = error?.status === 404;

  return (
    <>
      <PageHeader
        title="IASL"
        description="Adaptive admission control. What the controller sees, the one limit it moves, and why it moved it."
        actions={
          <>
            {lastOkAt && mode === "on" && <span className="hidden text-xs text-ink-300 sm:inline">Updated {fmtClock(lastOkAt)}</span>}
            <Button size="sm" variant="secondary" onClick={() => setPaused(!paused)} aria-pressed={paused}>{paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}{paused ? "Resume" : "Pause"}</Button>
            <Button size="sm" variant="ghost" onClick={refresh}><RefreshCw className="size-3.5" /> Refresh now</Button>
          </>
        }
      />

      {mode === "loading" && (
        <div className="grid gap-4">
          <div className="grid gap-4 lg:grid-cols-3"><Skeleton className="h-56" /><Skeleton className="h-56 lg:col-span-2" /></div>
          <Skeleton className="h-80" />
        </div>
      )}

      {mode === "offline" && (
        <ErrorState title={predatesIasl ? "This server does not have IASL" : "No answer from the API"} action={<Button size="sm" variant="secondary" onClick={refresh}>Retry now</Button>}>
          <p>{error?.message}</p>
          {predatesIasl && <p className="mt-2">IASL itself stays off unless <span className="font-mono text-ink-50">IASL_ENABLED=1</span> is set.</p>}
          <CodeBlock className="mt-3 w-full" title="start the server with IASL on" code={"IASL_ENABLED=1 .venv/bin/uvicorn app.main:app --port 8000"} />
        </ErrorState>
      )}

      {mode === "off" && (
        <div className="space-y-4">
          <IaslOffState />
          {config && <Settings config={config} />}
        </div>
      )}

      {mode === "on" && status && (
        <div className="space-y-4">
          {error && <ErrorState title="Polling is failing: this page shows the last good answer">{error.message}</ErrorState>}

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-1"><StateCard status={status} signals={signals} /></div>
            <div className="lg:col-span-2"><GateOrWaiting status={status} /></div>
          </div>

          <IaslChart history={history} decisions={decisions} status={status} />

          <div className="grid gap-4 lg:grid-cols-2">
            {signals.length > 0 ? <SignalsPanel signals={signals} /> : (
              <section className="panel p-5"><EmptyState title="Signals appear after the first analysed sample">They are the six numbers the controller compares with its thresholds.</EmptyState></section>
            )}
            <ControllerFacts status={status} />
          </div>

          <DecisionLog decisions={decisions} />

          {config && <Settings config={config} note={status.calibration} />}

          {unavailable.length > 0 && (
            <section aria-labelledby="iasl-unavailable">
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <h2 id="iasl-unavailable" className="text-[15px] font-medium text-ink-50">Not available</h2>
                <SourceBadge source="unavailable" />
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {unavailable.map(([what, why]) => <Unavailable key={what} what={what.replace(/_/g, " ")} requirement={why} />)}
              </div>
            </section>
          )}
        </div>
      )}
    </>
  );
}
