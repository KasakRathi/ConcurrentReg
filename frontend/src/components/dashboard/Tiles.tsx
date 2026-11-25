import type { ExperimentResult, OsLayerStatus } from "@/lib/types";
import { fmtInt, fmtMs, fmtNum, fmtRate, fmtSeconds } from "@/lib/format";
import { Metric, MetricGrid } from "./parts";

/** Live counters from GET /os-layer/status. Counters are cumulative since the server started. */
export function LiveTiles({ status }: { status: OsLayerStatus }) {
  const sem = status.db_semaphore;
  const avgSem = sem.acquisitions > 0 ? sem.wait_total_s / sem.acquisitions : null;
  return (
    <MetricGrid>
      <Metric label="Queue depth" value={status.queue.depth} unit={`/ ${status.queue.capacity}`} sub={`peak ${status.queue.max_depth}`} tone={status.queue.depth >= status.queue.capacity ? "rose" : "default"} />
      <Metric label="Active workers" value={status.workers.active} unit={`/ ${status.workers.configured}`} sub={`peak ${status.workers.max_active} · alive ${status.workers.alive}`} />
      <Metric label="Semaphore holders" value={sem.in_critical_section} unit={`/ ${sem.permits}`} sub={`${sem.waiting} waiting · peak wait ${sem.max_waiting}`} tone="violet" hint="Workers currently inside the database section" />
      <Metric label="Semaphore utilisation" value={fmtNum((sem.in_critical_section / sem.permits) * 100, 0)} unit="%" sub="holders / permits, right now" tone="violet" />
      <Metric label="Accepted" value={fmtInt(status.queue.accepted)} sub="requests placed in the queue" />
      <Metric label="Refused (queue full)" value={fmtInt(status.queue.rejected_queue_full)} sub={`${fmtInt(status.queue.rejected_shutting_down)} refused while shutting down`} tone={status.queue.rejected_queue_full > 0 ? "rose" : "default"} />
      <Metric label="Jobs finished" value={fmtInt(status.workers.jobs_finished)} sub={`${fmtInt(status.workers.jobs_started)} started · ${fmtInt(status.workers.unexpected_errors)} unexpected errors`} tone="mint" />
      <Metric label="Average waits" value={fmtSeconds(status.queue_wait.average_s)} sub={`in queue · ${fmtSeconds(avgSem)} for a permit`} hint="Queue wait and semaphore wait, averaged since server start" />
    </MetricGrid>
  );
}

const count = (e: ExperimentResult, c: keyof ExperimentResult["summary"]["category_counts"]) => e.summary.category_counts[c] ?? 0;

/** Summary of one imported result file, straight from its summary block. */
export function ExperimentTiles({ exp }: { exp: ExperimentResult }) {
  const s = exp.summary;
  const lat = s.latency_ms;
  const n = s.latency_sample_count;
  const offered = s.open_loop?.intended_requests ?? s.closed_loop?.intended_requests ?? s.total_requests;
  const completed = s.total_requests - count(exp, "NOT_DISPATCHED");
  const pNote = (min: number) => (n < min ? `only ${n} samples: this is close to the maximum` : `of ${fmtInt(n)} answered requests`);
  return (
    <div className="space-y-3">
      <MetricGrid>
        <Metric label="Requests offered" value={fmtInt(offered)} sub={s.arrival_model === "closed" ? "closed loop: set by the users' pace" : "intended by the schedule"} />
        <Metric label="Requests completed" value={fmtInt(completed)} sub={`${fmtInt(count(exp, "NOT_DISPATCHED"))} never dispatched`} />
        <Metric label="Achieved throughput" value={fmtNum(s.completed_requests_per_second, 1)} unit="req/s" sub="completed, any outcome, over the whole run" />
        <Metric label="Registrations / s" value={fmtNum(s.successful_registrations_per_second, 1)} unit="req/s" tone="mint" sub={`over ${fmtNum(s.elapsed_seconds, 2)} s`} />
      </MetricGrid>
      <MetricGrid>
        <Metric label="Latency, average" value={fmtMs(lat?.average)} sub="send-time, answered requests" />
        <Metric label="Latency p50" value={fmtMs(lat?.p50)} sub={`of ${fmtInt(n)} answered requests`} />
        <Metric label="Latency p95" value={fmtMs(lat?.p95)} sub={pNote(20)} />
        <Metric label="Latency p99" value={fmtMs(lat?.p99)} sub={pNote(100)} />
      </MetricGrid>
      <MetricGrid cols={5}>
        <Metric label="Registered" value={fmtInt(count(exp, "SUCCESS"))} tone="mint" sub="HTTP 201" />
        <Metric label="Duplicate" value={fmtInt(count(exp, "DUPLICATE"))} tone="violet" sub="already registered" />
        <Metric label="Course full" value={fmtInt(count(exp, "COURSE_FULL"))} tone="amber" sub="no seats left" />
        <Metric label="Queue full" value={fmtInt(count(exp, "QUEUE_FULL"))} tone="rose" sub="refused by the queue" />
        <Metric label="Server errors" value={fmtInt(count(exp, "SERVER_ERROR"))} tone={count(exp, "SERVER_ERROR") ? "rose" : "default"} sub="HTTP 5xx; database errors are reported as 500" hint="Transaction errors reach the client as HTTP 500" />
      </MetricGrid>
      <p className="text-xs text-ink-400">{s.open_loop ? <>Arrival rates: {fmtRate(s.open_loop.offered_rate_per_s)} offered, {fmtRate(s.open_loop.achieved_dispatch_rate_per_s)} dispatched.</> : "Closed loop: arrivals follow the users' pace, so there is no offered rate."}</p>
    </div>
  );
}
