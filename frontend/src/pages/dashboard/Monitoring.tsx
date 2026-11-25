import { Pause, Play, Trash2 } from "lucide-react";
import { useMonitor, useWindowedSamples } from "@/hooks/monitor";
import { ChartFrame } from "@/components/charts/common";
import { LiveChart } from "@/components/charts/LiveChart";
import { LiveTiles } from "@/components/dashboard/Tiles";
import { PageHeader, Section } from "@/components/dashboard/parts";
import { Button } from "@/components/ui/Button";
import { CodeBlock } from "@/components/ui/CodeBlock";
import { EmptyState, ErrorState, Skeleton, Unavailable } from "@/components/ui/States";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { buildServerCommand } from "@/lib/command";
import { fmtClock } from "@/lib/format";
import { COLORS } from "@/lib/theme";

export default function Monitoring() {
  const { status, error, paused, setPaused, intervalMs, setIntervalMs, clearSamples, refresh, samples: all, lastOkAt } = useMonitor();
  const samples = useWindowedSamples();
  const restarts = all.filter((s) => s.restart).length;

  return (
    <>
      <PageHeader
        title="Monitoring"
        description="Live counters of the OS layer, sampled from GET /os-layer/status by this browser. The server keeps no history: the charts start when you open the dashboard."
        actions={
          <>
            <label className="flex items-center gap-2 text-xs text-ink-300">Poll every
              <select value={intervalMs} onChange={(e) => setIntervalMs(Number(e.target.value))} className="rounded-md border border-ink-600 bg-ink-900 px-2 py-1.5 font-mono text-[12px] text-ink-50">
                {[1000, 2000, 5000].map((v) => <option key={v} value={v}>{v / 1000} s</option>)}
              </select>
            </label>
            <Button size="sm" variant="secondary" onClick={() => setPaused(!paused)} aria-pressed={paused}>{paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}{paused ? "Resume" : "Pause"}</Button>
            <Button size="sm" variant="ghost" onClick={clearSamples}><Trash2 className="size-3.5" /> Clear history</Button>
          </>
        }
      />

      {!status && !error && <div className="grid gap-3"><Skeleton className="h-28" /><Skeleton className="h-64" /></div>}
      {error && !status && (
        <ErrorState title="No answer from the API" action={<Button size="sm" variant="secondary" onClick={refresh}>Retry now</Button>}>
          <p>{error.message}</p>
          <CodeBlock className="mt-3 w-full" title="start the server" code={buildServerCommand(16, 4, 2)} />
        </ErrorState>
      )}

      {status && (
        <>
          {error && <ErrorState className="mb-4" title="Polling is failing: charts are paused at the last good sample">{error.message}</ErrorState>}
          <Section title="Current counters" source="live" sourceLabel={`Live API · ${lastOkAt ? fmtClock(lastOkAt) : ""}`}><LiveTiles status={status} /></Section>

          {samples.length < 3 ? (
            <EmptyState title="Collecting samples…" className="mb-10">Charts need a few polls. Send some traffic with the workload generator to see the queue, workers and semaphore react.</EmptyState>
          ) : (
            <Section title="Time series" source="live" note={`${samples.length} samples in this window. Rates are the difference between two polls divided by the time between them; a gap means the server restarted${restarts ? ` (${restarts} restart${restarts > 1 ? "s" : ""} seen)` : ""} or the API was unreachable.`}>
              <div className="grid gap-3 lg:grid-cols-2">
                <ChartFrame title="Queue depth" subtitle="Requests waiting for a worker" badge={<SourceBadge source="live" />}>
                  <LiveChart samples={samples} step series={[{ key: "depth", label: "Queue depth", color: COLORS.amber }]} referenceY={status.queue.capacity} referenceLabel={`capacity ${status.queue.capacity}`} />
                </ChartFrame>
                <ChartFrame title="Workers and semaphore" subtitle="Active workers, permit holders and workers waiting for a permit" badge={<SourceBadge source="live" />}>
                  <LiveChart samples={samples} step series={[
                    { key: "activeWorkers", label: "Active workers", color: COLORS.sky },
                    { key: "semHolders", label: "Holding a permit", color: COLORS.violet },
                    { key: "semWaiting", label: "Waiting for a permit", color: COLORS.amber },
                  ]} />
                </ChartFrame>
                <ChartFrame className="lg:col-span-2" title="Rates since the previous poll" subtitle="Requests per second as seen by the server's counters" badge={<SourceBadge source="live" />}>
                  <LiveChart samples={samples} series={[
                    { key: "acceptedPerS", label: "Accepted /s", color: COLORS.sky },
                    { key: "finishedPerS", label: "Finished /s", color: COLORS.mint },
                    { key: "rejectedPerS", label: "Refused (queue full) /s", color: COLORS.rose },
                  ]} />
                </ChartFrame>
              </div>
            </Section>
          )}
        </>
      )}

      <Section title="Not available" source="unavailable">
        <div className="grid gap-3 lg:grid-cols-2">
          <Unavailable what="Database lock-wait time" requirement="The API does not report InnoDB lock waits. It would need an endpoint backed by information_schema.innodb_trx or performance_schema." />
          <Unavailable what="Latency percentiles over time" requirement="The server does not record per-request latency in an endpoint. Per-run percentiles are available from imported result files." />
        </div>
      </Section>
    </>
  );
}
