import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  fetchIaslConfig, fetchIaslDecisions, fetchIaslMetrics, fetchIaslStatus, parseIaslConfig, parseIaslDecisions, parseIaslMetrics, parseIaslStatus,
  PREDATES_IASL_MESSAGE,
} from "./iaslApi";
import { makeDecision, makeHistory, makeMetrics, makeStatus } from "./iaslFixtures";

const OFF = { enabled: false, message: "IASL is switched off (IASL_ENABLED is not true). Nothing is installed on the request path." };
const CONFIG = {
  enabled: true, active: true, read_only: true, how_to_change: "set the IASL_* environment variables and restart the server", calibration: "PROVISIONAL",
  settings: { sampling_interval_s: 0.5, fallback_mode: "baseline" }, environment_variables: { sampling_interval_s: "IASL_SAMPLING_INTERVAL_S" },
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const stubFetch = (impl: (url: string, init?: RequestInit) => Promise<Response>) => {
  const fn = vi.fn(impl);
  vi.stubGlobal("fetch", fn);
  return fn;
};
afterEach(() => vi.unstubAllGlobals());

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try { await promise; } catch (e) { return e as ApiError; }
  throw new Error("expected the call to fail");
}

describe("parsers accept the real shapes", () => {
  it("status, metrics (with and without history), decisions and config", () => {
    expect(parseIaslStatus(makeStatus())).toMatchObject({ enabled: true, state: "HEALTHY" });
    expect(parseIaslStatus(makeStatus({ state: null, current_metrics: null }))).toMatchObject({ state: null });
    expect(parseIaslStatus(makeStatus({ last_decision: makeDecision(), last_control_action: makeDecision() }))).toMatchObject({ enabled: true });
    expect(parseIaslMetrics(makeMetrics())).toMatchObject({ enabled: true });
    expect(parseIaslMetrics(makeMetrics({ history: makeHistory(5) }))).toMatchObject({ history: expect.any(Array) });
    expect(parseIaslMetrics(makeMetrics({ sample: null, analysis: null }))).toMatchObject({ sample: null });
    expect(parseIaslDecisions({ enabled: true, returned: 1, kept: 1, note: "n", decisions: [makeDecision()] })).toMatchObject({ kept: 1 });
    expect(parseIaslDecisions({ enabled: true, returned: 0, kept: 0, note: "n", decisions: [] })).toMatchObject({ kept: 0 });
    expect(parseIaslConfig(CONFIG)).toMatchObject({ read_only: true });
    expect(parseIaslConfig({ ...CONFIG, enabled: false, active: false })).toMatchObject({ active: false });
  });
  it("every state the backend can report is accepted", () => {
    for (const state of ["HEALTHY", "UNDER_PRESSURE", "OVERLOADED"] as const) expect(parseIaslStatus(makeStatus({ state }))).toMatchObject({ state });
  });
});

describe("the off state is a value, not an error", () => {
  it("status, metrics and decisions return {enabled:false, message}", () => {
    expect(parseIaslStatus(OFF)).toEqual({ enabled: false, message: OFF.message });
    expect(parseIaslMetrics(OFF)).toEqual({ enabled: false, message: OFF.message });
    expect(parseIaslDecisions({ ...OFF, decisions: [] })).toEqual({ enabled: false, message: OFF.message });
  });
  it("an off answer without its message is not trusted", () => {
    for (const parse of [parseIaslStatus, parseIaslMetrics, parseIaslDecisions]) expect(() => parse({ enabled: false })).toThrow(ApiError);
  });
});

describe("parsers refuse anything else", () => {
  const garbage: unknown[] = ["<html>502 Bad Gateway</html>", null, undefined, 42, [], [{ enabled: true }], {}, { enabled: "yes" }, { detail: "Not Found" }];
  it("an HTML page, null, arrays and objects without 'enabled' are invalid for every endpoint", () => {
    for (const parse of [parseIaslStatus, parseIaslMetrics, parseIaslDecisions, parseIaslConfig]) {
      for (const bad of garbage) {
        const error = (() => { try { parse(bad); } catch (e) { return e as ApiError; } return null; })();
        expect(error, `${parse.name}(${JSON.stringify(bad)})`).toBeInstanceOf(ApiError);
        expect(error!.kind).toBe("invalid");
      }
    }
  });
  it("status missing a required part is invalid", () => {
    const { admission: _a, ...noAdmission } = makeStatus();
    const { fallback: _f, ...noFallback } = makeStatus();
    for (const bad of [noAdmission, noFallback, makeStatus({ state: "MELTING" as never }), { ...makeStatus(), loop: { ticks: "many" } }, { ...makeStatus(), running: "yes" },
      { ...makeStatus(), last_decision: { id: 1 } }, { ...makeStatus(), calibration: 5 }]) {
      expect(() => parseIaslStatus(bad)).toThrow(/\/iasl\/status shape/);
    }
  });
  it("metrics with a broken sample, analysis or history are invalid", () => {
    for (const bad of [{ ...makeMetrics(), sample: { wall_time: 5 } }, { ...makeMetrics(), analysis: { state: "HEALTHY" } }, { ...makeMetrics(), history: "no" },
      { ...makeMetrics(), history: [{ queue_utilization: 0.5 }] }, { ...makeMetrics(), sampling_interval_s: "fast" }]) {
      expect(() => parseIaslMetrics(bad)).toThrow(/\/iasl\/metrics shape/);
    }
  });
  it("decisions with a malformed entry or no list are invalid", () => {
    expect(() => parseIaslDecisions({ enabled: true, kept: 1, decisions: [{ id: 1 }] })).toThrow(/\/iasl\/decisions shape/);
    expect(() => parseIaslDecisions({ enabled: true, kept: 1, decisions: "x" })).toThrow(ApiError);
    expect(() => parseIaslDecisions({ enabled: true, decisions: [] })).toThrow(ApiError);
  });
  it("config missing its parts is invalid", () => {
    for (const bad of [{ ...CONFIG, settings: null }, { ...CONFIG, environment_variables: [] }, { ...CONFIG, read_only: "yes" }, { ...CONFIG, active: undefined }]) {
      expect(() => parseIaslConfig(bad)).toThrow(/\/iasl\/config shape/);
    }
  });
});

describe("requests", () => {
  it("call the right URLs through the /api proxy and clamp the query values the server enforces", async () => {
    const fetchMock = stubFetch(async (url) => json(url.includes("decisions") ? { enabled: true, returned: 0, kept: 0, note: "", decisions: [] } : makeMetrics()));
    await fetchIaslMetrics();
    await fetchIaslMetrics(120);
    await fetchIaslMetrics(5000);
    await fetchIaslMetrics(7.9);
    await fetchIaslDecisions();
    await fetchIaslDecisions(0);
    await fetchIaslDecisions(9999);
    await fetchIaslDecisions(37.6);
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "/api/iasl/metrics", "/api/iasl/metrics?history=120", "/api/iasl/metrics?history=120", "/api/iasl/metrics?history=7",
      "/api/iasl/decisions?limit=50", "/api/iasl/decisions?limit=1", "/api/iasl/decisions?limit=200", "/api/iasl/decisions?limit=37",
    ]);
  });
  it("status and config use their own paths and ask for JSON", async () => {
    const fetchMock = stubFetch(async (url) => json(url.endsWith("config") ? CONFIG : makeStatus()));
    await fetchIaslStatus();
    await fetchIaslConfig();
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/iasl/status", "/api/iasl/config"]);
    expect((fetchMock.mock.calls[0][1]?.headers as Record<string, string>).accept).toBe("application/json");
  });
  it("returns the off state as a value", async () => {
    stubFetch(async () => json(OFF));
    expect(await fetchIaslStatus()).toEqual({ enabled: false, message: OFF.message });
  });
});

describe("failures are typed", () => {
  it("HTTP 404 means the backend predates IASL, with a message that says what to do", async () => {
    stubFetch(async () => json({ detail: "Not Found" }, 404));
    for (const call of [() => fetchIaslStatus(), () => fetchIaslMetrics(), () => fetchIaslDecisions(), () => fetchIaslConfig()]) {
      const error = await failure(call());
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({ kind: "http", status: 404, message: PREDATES_IASL_MESSAGE });
    }
    expect(PREDATES_IASL_MESSAGE).toBe("This backend has no /iasl endpoints (it predates IASL). Restart it from the current code.");
  });
  it("other HTTP errors keep their status", async () => {
    stubFetch(async () => json({ detail: "boom" }, 500));
    expect(await failure(fetchIaslStatus())).toMatchObject({ kind: "http", status: 500, message: "GET /iasl/status returned HTTP 500" });
    stubFetch(async () => json({ detail: "bad" }, 422));
    expect(await failure(fetchIaslDecisions())).toMatchObject({ kind: "http", status: 422 });
  });
  it("a body that is not JSON is invalid, not a crash", async () => {
    stubFetch(async () => new Response("<html>proxy error</html>", { status: 200, headers: { "content-type": "text/html" } }));
    expect(await failure(fetchIaslStatus())).toMatchObject({ kind: "invalid", message: "GET /iasl/status did not return JSON." });
  });
  it("JSON of the wrong shape is invalid", async () => {
    stubFetch(async () => json({ hello: "world" }));
    expect(await failure(fetchIaslMetrics())).toMatchObject({ kind: "invalid" });
  });
  it("a network failure is unreachable", async () => {
    stubFetch(async () => { throw new TypeError("Failed to fetch"); });
    expect(await failure(fetchIaslStatus())).toMatchObject({ kind: "unreachable" });
  });
  it("a server that never answers times out as unreachable", async () => {
    stubFetch((_url, init) => new Promise((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))));
    expect(await failure(fetchIaslStatus(undefined, 25))).toMatchObject({ kind: "unreachable" });
  });
  it("a caller that cancels sees the abort, not a fake 'unreachable'", async () => {
    stubFetch((_url, init) => new Promise((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))));
    const controller = new AbortController();
    const pending = failure(fetchIaslStatus(controller.signal));
    controller.abort();
    const error = await pending;
    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as Error).name).toBe("AbortError");
  });
});
