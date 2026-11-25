# IASL Configuration

How to switch IASL on and off, every setting with its default and valid range, and how the settings behave at start-up and when the layer is
replaced. Every default and range below was read from `app/iasl/config.py` (class `IASLConfig`); if the code changes, the code wins.

> **Every numeric default is PROVISIONAL and UNCALIBRATED.** None is an experimentally validated value. They exist so the system can run. The
> evaluation in `IASL_EXPERIMENTS.md` tests the defaults *unmodified* and reports what happened; it does not establish that any value is a good one.

---

## 1. Switching IASL on and off

IASL is **off by default**. When it is off no IASL object exists, no hook is installed on the OS layer, no thread is started, and `/os-layer/status`
has no `admission` block: the request path is the original one.

```bash
# off (default): nothing to set
.venv/bin/uvicorn app.main:app --port 8000

# on, with all defaults
IASL_ENABLED=1 .venv/bin/uvicorn app.main:app --port 8000

# on, with the layer sized for a meaningful control range and one setting changed
IASL_ENABLED=true QUEUE_CAPACITY=200 WORKER_COUNT=8 DB_SEMAPHORE_PERMITS=4 IASL_FALLBACK_MODE=conservative \
  .venv/bin/uvicorn app.main:app --port 8000
```

`IASL_ENABLED` accepts `1 / true / yes / on` and `0 / false / no / off` (case-insensitive). Anything else is an error. An empty or whitespace-only value
means "use the default" for every variable.

**Size the layer first.** With the development defaults (queue capacity 16, 4 workers) the admission limit can only move between 4 and 16, which is
too narrow to be informative. The limit's range is derived from the layer (section 3), so a larger `QUEUE_CAPACITY` gives it room.

**Bad values stop start-up.** Settings are parsed once, when the application starts. A value that is not a number, is out of range, or breaks a
cross-setting rule raises `ValueError` naming the environment variable, and the server does not start, the same convention as `QUEUE_CAPACITY`,
`WORKER_COUNT` and `DB_SEMAPHORE_PERMITS`:

```text
$ IASL_ENABLED=1 IASL_SAMPLING_INTERVAL_S=fast .venv/bin/uvicorn app.main:app
ValueError: IASL_SAMPLING_INTERVAL_S must be a number, got 'fast'

$ IASL_ENABLED=1 IASL_QUEUE_UTIL_PRESSURE=0.9 .venv/bin/uvicorn app.main:app
ValueError: IASL_QUEUE_UTIL_PRESSURE and IASL_QUEUE_UTIL_OVERLOAD must satisfy 0 < pressure < overload and at most 1.0, got 0.9 and 0.85
```

Settings are validated even when IASL is off (`IASL_ENABLED` unset), so a typo is never silently ignored; but they have no effect until
`IASL_ENABLED` is true.

---

## 2. All settings

Types: integers must be whole numbers (`2.5` is rejected); numbers must be finite (`nan`, `inf` are rejected); booleans are rejected as numbers.

### 2.1 Loop and safety timing

| Variable | Default | Valid range / rule | Meaning |
|---|---|---|---|
| `IASL_ENABLED` | `false` | see section 1 | master switch |
| `IASL_SAMPLING_INTERVAL_S` | `0.5` | 0.1 to 10 | seconds between control-loop ticks |
| `IASL_STALE_METRIC_SECONDS` | `2.0` | at least 2 x sampling interval | a sample older than this is treated as stale: the analyzer holds its state |
| `IASL_WATCHDOG_SECONDS` | `5.0` | at least 3 x sampling interval | if the controller thread has not signalled life this long, the request path uses the fallback limit on its own |
| `IASL_FALLBACK_MODE` | `baseline` | `baseline` or `conservative` (case-insensitive) | what the limit becomes in fallback (section 4) |
| `IASL_FALLBACK_AFTER_FAILURES` | `3` | whole number, at least 1 | consecutive failed ticks that put the system in fallback |
| `IASL_FALLBACK_AFTER_DEGRADED` | `10` | whole number, at least 1 | consecutive untrusted samples (invalid, stale or degraded) that do the same |
| `IASL_FALLBACK_RECOVERY_SAMPLES` | `10` | whole number, at least 1 | consecutive healthy ticks needed to leave fallback |

### 2.2 The one controlled parameter: the admission depth limit

A request is admitted only while fewer than L requests are waiting in the queue. `L` moves between a floor and the queue's capacity.

| Variable | Default | Valid range / rule | Meaning |
|---|---|---|---|
| `IASL_ADMISSION_MIN` | automatic: worker count | whole number, at least 1; must not exceed `IASL_ADMISSION_MAX` | the floor of L |
| `IASL_ADMISSION_MAX` | automatic: queue capacity | whole number, at least 1; always capped at the queue capacity | the ceiling of L |
| `IASL_ADMISSION_INITIAL` | automatic: the maximum | whole number between min and max | L at start-up. The automatic value means IASL starts exactly as permissive as no IASL |
| `IASL_ADJUSTMENT_STEP` | `0.10` | 0.01 to 0.5 | one normal move = this fraction of (max - min), at least 1 |
| `IASL_OVERLOAD_STEP_MULTIPLIER` | `2` | whole number, 1 to 4 | the largest single move is step x this (used when overloaded) |
| `IASL_COOLDOWN_SECONDS` | `2.0` | at least 0 and at least the sampling interval | a DECREASE may follow the previous change after this long |
| `IASL_INCREASE_COOLDOWN_SECONDS` | `4.0` | at least `IASL_COOLDOWN_SECONDS` | an INCREASE may follow the previous change after this long (relaxing is slower than tightening) |
| `IASL_REVERSAL_LOCKOUT_SECONDS` | `8.0` | at least `IASL_COOLDOWN_SECONDS` | an INCREASE may not follow a DECREASE sooner than this |
| `IASL_MAX_REVERSALS` | `3` | whole number, at least 1 | direction reversals within the window that count as oscillation |
| `IASL_OSCILLATION_WINDOW_SECONDS` | `60` | at least 1 | the window those reversals are counted in |
| `IASL_OSCILLATION_HOLD_SECONDS` | `30` | at least 1 | how long all changes are held once oscillation is detected |

### 2.3 State thresholds (how the analyzer sees the system)

Each pair is `pressure < overload`, with `0 < pressure < overload`, and the ratios also at most 1. A signal's level rises when its value reaches the
*enter* threshold and falls only below `enter x IASL_EXIT_RATIO`.

| Variable | Default | Signal | Class |
|---|---|---|---|
| `IASL_QUEUE_UTIL_PRESSURE` / `_OVERLOAD` | `0.50` / `0.85` | queue depth / physical queue capacity (smoothed) | primary |
| `IASL_QUEUE_WAIT_P95_PRESSURE_S` / `_OVERLOAD_S` | `0.10` / `0.50` (seconds) | p95 queue wait over the latency window (no upper limit) | primary |
| `IASL_REJECTION_RATE_PRESSURE` / `_OVERLOAD` | `0.01` / `0.05` | queue-full refusals / arrivals, per interval | primary |
| `IASL_ERROR_RATE_PRESSURE` / `_OVERLOAD` | `0.02` / `0.10` | `ERROR` outcomes / completions, per interval | primary |
| `IASL_WORKER_UTIL_PRESSURE` / `_OVERLOAD` | `0.90` / `0.99` | active workers / alive workers (smoothed) | corroborating |
| `IASL_SEM_WAIT_RATIO_PRESSURE` / `_OVERLOAD` | `1.0` / `3.0` (no upper limit) | semaphore waiters / permits (smoothed) | corroborating |

Admission-control refusals are deliberately **not** a signal (they would feed back on themselves), and queue utilisation is measured against the
queue's physical capacity, not against the current limit.

### 2.4 Analyzer smoothing and hysteresis

| Variable | Default | Valid range / rule | Meaning |
|---|---|---|---|
| `IASL_EXIT_RATIO` | `0.7` | 0.1 to 0.95 | a signal leaves a level only below `enter x this` |
| `IASL_SMOOTHING_SAMPLES` | `3` | whole number, 1 to 20 | the gauges are averaged over this many samples |
| `IASL_ESCALATE_SAMPLES` | `2` | whole number, at least 1 | consecutive worse samples needed to move to a worse state |
| `IASL_DEESCALATE_SAMPLES` | `5` | whole number, at least 1 | consecutive better samples needed to move one state better |
| `IASL_MIN_PRIMARY_SIGNALS` | `2` | whole number, 1 to 4 | fewer primary signals than this makes the sample `DEGRADED` and the state is held |

### 2.5 Metrics window and decision log

| Variable | Default | Valid range / rule | Meaning |
|---|---|---|---|
| `IASL_LATENCY_WINDOW_SECONDS` | `5` | 0.5 to 3600 | how far back the latency percentiles look |
| `IASL_LATENCY_RING_SIZE` | `2048` | whole number, 16 to 1,000,000 | most completions kept for the percentiles |
| `IASL_MIN_LATENCY_SAMPLES` | `20` | whole number, at least 1 | fewer samples than this: percentiles are `null`, never extrapolated |
| `IASL_DECISION_LOG_SIZE` | `500` | whole number, 10 to 10,000 | decisions kept in memory (`GET /iasl/decisions`) |

The brief's illustrative `IASL_HEALTHY_THRESHOLD` / `IASL_PRESSURE_THRESHOLD` / `IASL_OVERLOAD_THRESHOLD` do not exist: one scalar cannot describe a
multi-signal analyzer, so each signal has its own pair.

---

## 3. How the admission bounds are resolved

`IASL_ADMISSION_*` are resolved against the layer's size when IASL attaches to it (`IASLConfig.resolve_bounds`):

| Value | Automatic rule |
|---|---|
| maximum | `IASL_ADMISSION_MAX` if given, **capped at the queue capacity**; otherwise the queue capacity |
| minimum | `IASL_ADMISSION_MIN` if given; otherwise the **worker count** (if that exceeds the maximum, it is reduced to the maximum) |
| initial | `IASL_ADMISSION_INITIAL` if given; otherwise the **maximum** |

At `L = maximum = queue capacity` the admission check is skipped entirely and behaviour is identical to running without IASL.

Example: queue 200, workers 8, nothing set: bounds 8 / 200 / 200, step `round(0.10 x 192) = 19`, largest single move 38.

**At start-up** an impossible explicit combination (for example `IASL_ADMISSION_MIN=50` with a queue of 10, or an initial value outside min..max)
raises `ValueError` naming the variable and the server does not start. Combinations that can be checked without the layer (min greater than max when
both are set, initial outside them) fail while the settings are parsed.

---

## 4. Fallback

Fallback is a safe, bounded state the system enters when IASL cannot be trusted. The limit in fallback comes from `IASL_FALLBACK_MODE`:

| Mode | Limit in fallback |
|---|---|
| `baseline` (default) | the queue capacity: identical to running without IASL |
| `conservative` | `max(minimum, capacity // 2)` |

Fallback is entered when `IASL_FALLBACK_AFTER_FAILURES` consecutive ticks fail, or `IASL_FALLBACK_AFTER_DEGRADED` consecutive samples are untrusted, and it
is left after `IASL_FALLBACK_RECOVERY_SAMPLES` consecutive healthy ticks (control then resumes stepwise from the fallback value, with the cooldown applied
first). Independently of the controller thread, the request path switches to the fallback limit if no heartbeat arrives within
`IASL_WATCHDOG_SECONDS`. Fallback never raises a limit above the queue capacity and never lowers it below 1.

---

## 5. Monitoring: read-only

The settings above can only be changed through the environment, at start-up. **There is no endpoint that changes IASL**; restart the server to change a
value. The four endpoints are `GET` only (any other method returns 405):

| Endpoint | Shows |
|---|---|
| `GET /iasl/status` | on or off, current state and why, key metrics, the limit in force and its bounds, fallback state, the last control action, the last decision and its reason, loop counters |
| `GET /iasl/metrics[?history=N]` | the latest sample split into instantaneous / interval / window values, the analysis behind the state, the metrics that are unavailable and why; `history` (0 to 120) adds recent samples |
| `GET /iasl/decisions[?limit=N]` | the most recent decisions, oldest first (`limit` 1 to 200, default 50); repeated idle or blocked ticks are counted in `suppressed_since_last`, not listed |
| `GET /iasl/config` | the settings in force, the environment variable for each, the resolved bounds, and the calibration warning |

When IASL is off the first three answer `{"enabled": false, "message": ...}` (and `/iasl/decisions` an empty list); `/iasl/config` still shows the settings that
would apply. When IASL is on, `GET /os-layer/status` also carries an additive `admission` block (`enabled`, `rejected`, `limit`, `configured_limit`,
`fallback`, `watchdog_tripped`); it is absent when IASL is off.

Every decision is also written as one JSON line (`"event": "iasl_decision"`) on the `iasl` logger.

---

## 6. Interaction with `POST /demo/os-layer`

The demo API can replace the whole queue/worker/semaphore layer while the server runs (only when `CREG_DEMO_CONTROLS=1`). If IASL is on, it is
re-attached to the **new** layer *before* the new layer takes traffic:

* the bounds are recomputed from the new queue capacity and worker count;
* a lenient resolution is used: an explicit `IASL_ADMISSION_*` value that no longer fits is **clamped**, not rejected, because the server is already running;
* the controller, analyzer and metrics history are reset and a `RESET` decision is recorded; the first sample after the swap is treated as a restart;
* all the new layer's counters start at zero.

Result files written by `/demo/runs` record whether IASL was on and its configuration and final state under `server.iasl`.

---

## 7. Running the tests with IASL enabled

The normal test fixtures build servers with IASL explicitly off. To run the existing suite with IASL really on (all-default settings), use the plugin:

```bash
set -a; source .demo.env; set +a          # MySQL test database (name must end in _test)
PYTHONPATH=. .venv/bin/python -m pytest -p tests.iasl_enabled_plugin --ignore-glob='tests/test_iasl_*'
```

The plugin wraps `create_app` so every server a test builds has IASL enabled, and sets `IASL_ENABLED=1` for the module-level app. It refuses to run unless
`TEST_DATABASE_URL` names a database ending in `_test`. Do not run the IASL tests themselves under it: four of them assert "IASL is off" and the plugin
contradicts that on purpose. Details and results are in `IASL_TESTING.md`.
