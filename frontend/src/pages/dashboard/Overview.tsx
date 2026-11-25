import { Link } from "react-router-dom";
import { Upload } from "lucide-react";
import { useMonitor, useWindowedSamples } from "@/hooks/monitor";
import { useResults } from "@/hooks/results-store";
import { ChartFrame } from "@/components/charts/common";
import { LiveChart } from "@/components/charts/LiveChart";
import { OutcomeBars, MiniAreaThroughput } from "@/components/charts/ResultCharts";
import { ExperimentTiles, LiveTiles } from "@/components/dashboard/Tiles";
import { PageHeader, Section } from "@/components/dashboard/parts";
import { ButtonLink, Button } from "@/components/ui/Button";
import { CodeBlock } from "@/components/ui/CodeBlock";
import { EmptyState, ErrorState, Skeleton, Unavailable } from "@/components/ui/States";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { COLORS } from "@/lib/theme";
import { buildServerCommand } from "@/lib/command";
import { looksOffline } from "@/lib/api";

export default function Overview() {
  const { status, error, refresh } = useMonitor();
  const samples = useWindowedSamples();
  const { items, selectedId, ready } = useResults();
  const selected = items.find((i) => i.exp.experiment_id === selectedId)?.exp;

  return (
    <>
      <PageHeader title="Overview" description="Live counters from the running server first, then the evidence from a recorded run. The two are never mixed." actions={<ButtonLink to="/dashboard/workloads" variant="primary" size="sm">Configure a workload</ButtonLink>} />

      <Section title="Live OS layer" source="live" note="Counters from GET /os-layer/status, polled by this browser. They count requests since the server started and describe the queue, workers and semaphore, not the database.">
        {!status && !error && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[104px]" />)}</div>}
        {error && !status && (
          <ErrorState title={looksOffline(error) ? "The ConcurrentReg API is not reachable" : "The API answered unexpectedly"} action={<Button size="sm" variant="secondary" onClick={refresh}>Retry now</Button>}>
            <p>{error.message}</p>
            <p className="mt-2 text-ink-300">Nothing is shown in place of live data. Start the server, then this panel fills in on its own:</p>
            <CodeBlock className="mt-3 w-full" title="terminal" code={buildServerCommand(16, 4, 2)} />
          </ErrorState>
        )}
        {status && (
          <>
            {error && <ErrorState className="mb-3" title="Polling failed: showing the last answer received">{error.message}</ErrorState>}
            <LiveTiles status={status} />
            {samples.length > 2 && (
              <ChartFrame className="mt-3" title="Queue depth since this page was opened" subtitle="One point per poll, taken by this browser. History is not stored by the server and is lost on reload." badge={<SourceBadge source="live" />}>
                <LiveChart samples={samples} step height={160} series={[{ key: "depth", label: "Queue depth", color: COLORS.amber }]} referenceY={status.queue.capacity} referenceLabel={`capacity ${status.queue.capacity}`} />
              </ChartFrame>
            )}
          </>
        )}
      </Section>

      <Section title="Selected experiment" source="file" note={selected ? <>From the result file <code className="text-ink-200">{selected.experiment_id}</code>, a recorded past run, not the current state of the server. <Link className="text-mint hover:underline" to={`/dashboard/results/${encodeURIComponent(selected.experiment_id)}`}>Open full results</Link></> : undefined}>
        {!ready && <Skeleton className="h-40" />}
        {ready && !selected && (
          <EmptyState title="No experiment loaded" icon={<Upload className="size-6" />} action={<ButtonLink to="/dashboard/experiments" variant="secondary" size="sm">Import a result file</ButtonLink>}>
            The server does not keep run history. Run the workload generator, then import its JSON file from <code className="text-ink-100">results/</code>. The throughput, latency and outcome tiles are computed from that file.
          </EmptyState>
        )}
        {selected && (
          <>
            <ExperimentTiles exp={selected} />
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <ChartFrame title="Completed requests per second" badge={<SourceBadge source="file" />}><MiniAreaThroughput exp={selected} /></ChartFrame>
              <ChartFrame title="Outcome distribution" badge={<SourceBadge source="file" />}><OutcomeBars exp={selected} /></ChartFrame>
            </div>
          </>
        )}
      </Section>

      <Section title="Not available yet" source="unavailable" note="These were requested for the overview. The backend does not expose them today, so they are not shown, and nothing stands in for them.">
        <div className="grid gap-3 lg:grid-cols-3">
          <Unavailable what="Database lock-wait metrics" requirement="Needs a new endpoint that reads InnoDB lock waits (information_schema.innodb_trx or performance_schema) and the PROCESS privilege. The test suite reads them, the API does not." />
          <Unavailable what="Live latency percentiles (p95, p99)" requirement="The server only logs per-request timings. A metrics endpoint with a latency histogram would be needed. Percentiles above come from result files." />
          <Unavailable what="Live registration outcomes" requirement="Successes, duplicates and full-course answers are counted only by the client (result files) and in server logs, not by the API." />
        </div>
      </Section>
    </>
  );
}
