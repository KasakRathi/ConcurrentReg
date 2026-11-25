import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, fetchOsLayerStatus } from "@/lib/api";
import type { OsLayerStatus } from "@/lib/types";

/** One poll of GET /os-layer/status, plus rates computed from the previous poll. Taken by THIS browser. */
export interface Sample {
  t: number; // epoch ms when the response arrived
  depth: number;
  activeWorkers: number;
  semHolders: number;
  semWaiting: number;
  accepted: number;
  rejectedFull: number;
  finished: number;
  acceptedPerS: number | null;
  rejectedPerS: number | null;
  finishedPerS: number | null;
  restart: boolean; // counters went down: the server was restarted between two polls
}

const MAX_SAMPLES = 1800; // 1 hour at 2 s

interface MonitorState {
  status: OsLayerStatus | null;
  error: ApiError | null;
  samples: Sample[];
  lastOkAt: number | null;
  paused: boolean;
  intervalMs: number;
  /** Only samples newer than this many ms are shown (0 = everything this browser has collected). */
  windowMs: number;
  setWindowMs: (value: number) => void;
  setPaused: (value: boolean) => void;
  setIntervalMs: (value: number) => void;
  clearSamples: () => void;
  refresh: () => void;
}

const Ctx = createContext<MonitorState | null>(null);

export function MonitorProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<OsLayerStatus | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [lastOkAt, setLastOkAt] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const [intervalMs, setIntervalMs] = useState(2000);
  const [windowMs, setWindowMs] = useState(0);
  const [tick, setTick] = useState(0);
  const previous = useRef<{ status: OsLayerStatus; t: number } | null>(null);

  useEffect(() => {
    if (paused) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const next = await fetchOsLayerStatus(controller.signal);
        const t = Date.now();
        const before = previous.current;
        const restart = !!before && next.queue.accepted < before.status.queue.accepted;
        const dt = before ? (t - before.t) / 1000 : 0;
        const rate = (now: number, then: number | undefined) => (before && !restart && dt > 0 && then !== undefined ? Math.max(0, (now - then) / dt) : null);
        const sample: Sample = {
          t,
          depth: next.queue.depth,
          activeWorkers: next.workers.active,
          semHolders: next.db_semaphore.in_critical_section,
          semWaiting: next.db_semaphore.waiting,
          accepted: next.queue.accepted,
          rejectedFull: next.queue.rejected_queue_full,
          finished: next.workers.jobs_finished,
          acceptedPerS: rate(next.queue.accepted, before?.status.queue.accepted),
          rejectedPerS: rate(next.queue.rejected_queue_full, before?.status.queue.rejected_queue_full),
          finishedPerS: rate(next.workers.jobs_finished, before?.status.workers.jobs_finished),
          restart,
        };
        previous.current = { status: next, t };
        setStatus(next);
        setError(null);
        setLastOkAt(t);
        setSamples((all) => [...all, sample].slice(-MAX_SAMPLES));
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(e instanceof ApiError ? e : new ApiError("unreachable", "Unexpected error while polling the API."));
        previous.current = null; // do not compute a rate across an outage
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, intervalMs);
    };
    void poll();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [paused, intervalMs, tick]);

  const clearSamples = useCallback(() => setSamples([]), []);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  const value = useMemo<MonitorState>(
    () => ({ status, error, samples, lastOkAt, paused, intervalMs, windowMs, setWindowMs, setPaused, setIntervalMs, clearSamples, refresh }),
    [status, error, samples, lastOkAt, paused, intervalMs, windowMs, clearSamples, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useMonitor(): MonitorState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useMonitor must be used inside <MonitorProvider>");
  return value;
}

/** Samples inside the selected time window. */
export function useWindowedSamples(): Sample[] {
  const { samples, windowMs } = useMonitor();
  return useMemo(() => {
    if (!windowMs || samples.length === 0) return samples;
    const cutoff = samples[samples.length - 1].t - windowMs;
    return samples.filter((s) => s.t >= cutoff);
  }, [samples, windowMs]);
}
