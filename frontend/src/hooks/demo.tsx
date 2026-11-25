import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  DemoError, getCurrentRun, getInfo, getServerResult, getState, getVerify, startRun, startVerify, getRun, resetData,
  type DemoInfo, type DemoState, type RunJob, type RunRequest, type VerifySnapshot,
} from "@/lib/demoApi";
import { parseExperiment } from "@/lib/results";
import type { ExperimentResult } from "@/lib/types";
import { useResults } from "./results-store";

// ----------------------------------------------------------------------------- server capabilities

interface InfoCtx {
  info: DemoInfo | null;
  error: DemoError | null;
  refresh: () => void;
}
const Info = createContext<InfoCtx | null>(null);

/** Asks GET /demo/info on mount and every 10 s. Whether the demo controls are on is read from the server, never assumed. */
export function DemoProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<DemoInfo | null>(null);
  const [error, setError] = useState<DemoError | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    const load = () =>
      getInfo().then(
        (v) => { if (live) { setInfo(v); setError(null); } },
        (e) => { if (live) setError(e instanceof DemoError ? e : new DemoError("unreachable", "Unexpected error")); },
      );
    void load();
    const id = setInterval(load, 10000);
    return () => { live = false; clearInterval(id); };
  }, [tick]);
  const refresh = useCallback(() => setTick((n) => n + 1), []);
  const value = useMemo(() => ({ info, error, refresh }), [info, error, refresh]);
  return <Info.Provider value={value}>{children}</Info.Provider>;
}

export function useDemoInfo(): InfoCtx {
  const v = useContext(Info);
  if (!v) throw new Error("useDemoInfo must be used inside <DemoProvider>");
  return v;
}

// ----------------------------------------------------------------------------- live database state

/** The database's seats and invariants. Polled fast while a run is going, slowly otherwise. */
export function useDemoState(enabled: boolean, fast: boolean) {
  const [state, setState] = useState<DemoState | null>(null);
  const [error, setError] = useState<DemoError | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    const load = () =>
      getState().then(
        (v) => { if (live) { setState(v); setError(null); } },
        (e) => { if (live) setError(e instanceof DemoError ? e : new DemoError("unreachable", "Unexpected error")); },
      );
    void load();
    const id = setInterval(load, fast ? 500 : 4000);
    return () => { live = false; clearInterval(id); };
  }, [enabled, fast, tick]);
  const refresh = useCallback(() => setTick((n) => n + 1), []);
  return { state, error, refresh, setState };
}

export async function resetAndGet(): Promise<DemoState> {
  return resetData();
}

// ----------------------------------------------------------------------------- running an experiment

/**
 * Starts a run on the server, follows its progress, and when it finishes downloads the generator's result file
 * and adds it to this browser's experiments. Nothing is simulated: the numbers come from the finished run.
 */
export function useDemoRun() {
  const { addExperiment } = useResults();
  const [job, setJob] = useState<RunJob | null>(null);
  const [experiment, setExperiment] = useState<ExperimentResult | null>(null);
  const [error, setError] = useState<DemoError | null>(null);
  const [starting, setStarting] = useState(false);
  const finishing = useRef<string | null>(null);

  const finish = useCallback(async (done: RunJob) => {
    if (!done.experiment_id || finishing.current === done.job_id) return;
    finishing.current = done.job_id;
    try {
      const doc = await getServerResult(done.experiment_id);
      const exp = parseExperiment(JSON.stringify(doc));
      await addExperiment(exp, `${exp.experiment_id}.json (from the server)`);
      setExperiment(exp);
    } catch (e) {
      setError(e instanceof DemoError ? e : new DemoError("http", e instanceof Error ? e.message : "Could not load the result file"));
    }
  }, [addExperiment]);

  // follow a running job
  useEffect(() => {
    if (!job || job.status !== "running") return;
    let live = true;
    const id = setInterval(async () => {
      try {
        const next = await getRun(job.job_id);
        if (!live) return;
        setJob(next);
        if (next.status === "done") void finish(next);
      } catch (e) {
        if (live) setError(e instanceof DemoError ? e : new DemoError("unreachable", "Lost contact with the server"));
      }
    }, 300);
    return () => { live = false; clearInterval(id); };
  }, [job, finish]);

  // after a page reload: pick up a run that is still going on the server
  useEffect(() => {
    getCurrentRun().then((c) => { if (c.status === "running") setJob(c); }, () => undefined);
  }, []);

  const start = useCallback(async (request: RunRequest) => {
    setStarting(true);
    setError(null);
    setExperiment(null);
    finishing.current = null;
    try {
      setJob(await startRun(request));
    } catch (e) {
      setError(e instanceof DemoError ? e : new DemoError("http", "Could not start the run"));
    } finally {
      setStarting(false);
    }
  }, []);

  const clear = useCallback(() => { setJob(null); setExperiment(null); setError(null); }, []);
  return { job, experiment, error, starting, running: job?.status === "running", start, clear };
}

// ----------------------------------------------------------------------------- running the project's tests

export function useVerification() {
  const [snap, setSnap] = useState<VerifySnapshot>({ status: "none" });
  const [error, setError] = useState<DemoError | null>(null);

  useEffect(() => {
    getVerify().then((s) => { if (s.status !== "none") setSnap(s); }, () => undefined);
  }, []);

  useEffect(() => {
    if (snap.status !== "running") return;
    let live = true;
    const id = setInterval(async () => {
      try {
        const s = await getVerify();
        if (live) setSnap(s);
      } catch (e) {
        if (live) setError(e instanceof DemoError ? e : new DemoError("unreachable", "Lost contact with the server"));
      }
    }, 500);
    return () => { live = false; clearInterval(id); };
  }, [snap.status]);

  const start = useCallback(async () => {
    setError(null);
    try {
      setSnap(await startVerify());
    } catch (e) {
      setError(e instanceof DemoError ? e : new DemoError("http", "Could not start the test run"));
    }
  }, []);
  return { snap, error, start, running: snap.status === "running" };
}
