import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { fetchIaslConfig, fetchIaslDecisions, fetchIaslMetrics, fetchIaslStatus } from "@/lib/iaslApi";
import type { IaslConfigView, IaslDecision, IaslHistoryRow, IaslMetrics, IaslStatus } from "@/lib/iaslTypes";

export type IaslMode = "loading" | "off" | "offline" | "on";

export interface IaslView {
  mode: IaslMode;
  /** Set when the latest status poll failed. In mode "on" the data shown is the last good answer. */
  error: ApiError | null;
  status: IaslStatus | null;
  metrics: IaslMetrics | null;
  /** Recent samples, oldest first (GET /iasl/metrics?history=120). */
  history: IaslHistoryRow[];
  /** Decision log, oldest first (GET /iasl/decisions?limit=200). */
  decisions: IaslDecision[];
  config: IaslConfigView | null;
  lastOkAt: number | null;
  paused: boolean;
  setPaused: (paused: boolean) => void;
  refresh: () => void;
}

interface Data {
  mode: IaslMode;
  error: ApiError | null;
  status: IaslStatus | null;
  metrics: IaslMetrics | null;
  decisions: IaslDecision[];
  lastOkAt: number | null;
}

const EMPTY: Data = { mode: "loading", error: null, status: null, metrics: null, decisions: [], lastOkAt: null };
const toApiError = (e: unknown) => (e instanceof ApiError ? e : new ApiError("unreachable", "Unexpected error while polling the IASL API."));

/**
 * Polls the read-only IASL endpoints while the calling page is mounted (no provider needed): status, recent metrics history and the
 * decision log every tick, the config until it has been read once. One failing request never blanks the others, polls never overlap,
 * and nothing is stored or shown unless the server really sent it.
 */
export function useIasl(options: { intervalMs?: number } = {}): IaslView {
  const intervalMs = options.intervalMs ?? 1000;
  const [data, setData] = useState<Data>(EMPTY);
  const [config, setConfig] = useState<IaslConfigView | null>(null);
  const [paused, setPaused] = useState(false);
  const [tick, setTick] = useState(0);
  const haveConfig = useRef(false);

  useEffect(() => {
    if (paused) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      const wantConfig = !haveConfig.current;
      const [statusR, metricsR, decisionsR, configR] = await Promise.allSettled([
        fetchIaslStatus(controller.signal),
        fetchIaslMetrics(120, controller.signal),
        fetchIaslDecisions(200, controller.signal),
        wantConfig ? fetchIaslConfig(controller.signal) : Promise.resolve(null),
      ]);
      if (controller.signal.aborted) return;
      const now = Date.now();

      if (configR.status === "fulfilled" && configR.value) {
        haveConfig.current = true;
        setConfig(configR.value);
      }
      setData((prev) => {
        if (statusR.status === "rejected") {
          const error = toApiError(statusR.reason);
          // keep showing the last good answer if there was one; otherwise this is the first contact and it failed
          return prev.mode === "on" ? { ...prev, error } : { ...EMPTY, mode: "offline", error };
        }
        if (!statusR.value.enabled) return { mode: "off", error: null, status: null, metrics: null, decisions: [], lastOkAt: now };
        const metrics = metricsR.status === "fulfilled" && metricsR.value.enabled ? metricsR.value : prev.metrics;
        const decisions = decisionsR.status === "fulfilled" && decisionsR.value.enabled ? decisionsR.value.decisions : prev.decisions;
        return { mode: "on", error: null, status: statusR.value, metrics, decisions, lastOkAt: now };
      });
      if (!controller.signal.aborted) timer = setTimeout(poll, intervalMs);
    };
    void poll();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [paused, intervalMs, tick]);

  const refresh = useCallback(() => setTick((n) => n + 1), []);
  return {
    mode: data.mode, error: data.error, status: data.status, metrics: data.metrics,
    history: data.metrics?.history ?? [], decisions: data.decisions, config, lastOkAt: data.lastOkAt, paused, setPaused, refresh,
  };
}
